"""
CropSim Web - Versão de Produção
Simulação de crescimento de milho (CROPSIM simplificado)
Inclui análise de sensibilidade com variação configurável.
"""

import os
import math
import json
import traceback
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# ============================================================================
# CONFIGURAÇÃO
# ============================================================================
app = Flask(__name__)
CORS(app)  # libera acesso do seu site da Hostinger

WORKDIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(WORKDIR, exist_ok=True)


# ============================================================================
# FUNÇÕES DE LEITURA DOS ARQUIVOS
# ============================================================================
def ler_meteo(caminho):
    """Lê arquivo meteorológico (.met) e retorna listas diárias."""
    with open(caminho, 'r', encoding='latin-1') as f:
        linhas = f.read().splitlines()

    Rad, Tmin, Tmax, Vap, Vento, Chuva, Tmed = [], [], [], [], [], [], []
    for i in range(4, 369):   # 365 dias
        a = linhas[i].split()
        Rad.append(float(a[3]))
        Tmin.append(float(a[4]))
        Tmax.append(float(a[5]))
        Vap.append(float(a[6]))
        Vento.append(float(a[7]))
        Chuva.append(float(a[8]))
        Tmed.append((Tmin[-1] + Tmax[-1]) / 2)

    return {
        'Rad': Rad, 'Tmin': Tmin, 'Tmax': Tmax,
        'Vap': Vap, 'Vento': Vento, 'Chuva': Chuva, 'Tmed': Tmed
    }

def ler_cultura(caminho):
    """Lê arquivo .crp e retorna dicionário com todos os parâmetros."""
    with open(caminho, 'r', encoding='latin-1') as f:
        linhas = f.read().splitlines()

    tsum1 = float(linhas[16].split()[0])
    tsum2 = float(linhas[17].split()[0])
    tb    = float(linhas[18].split()[0])
    msi   = float(linhas[22].split()[0])
    iafi  = float(linhas[23].split()[0])
    vida  = int(float(linhas[27].split()[0]))
    sla1  = float(linhas[28].split()[0])
    sla2  = float(linhas[29].split()[0])
    kext  = float(linhas[33].split()[0])
    rue   = float(linhas[34].split()[0])

    ec = [float(linhas[i].split()[0]) for i in range(57, 61)]
    q10 = float(linhas[64].split()[0])
    frm = [float(linhas[i].split()[0]) for i in range(65, 69)]

    fdvs, f = [], []
    for i in range(74, 81):
        a = linhas[i].split()
        fdvs.append(float(a[0]))
        f.append([float(a[j]) for j in range(1, 5)])

    return {
        'tsum1': tsum1, 'tsum2': tsum2, 'tb': tb,
        'msi': msi, 'iafi': iafi, 'vida': vida,
        'sla1': sla1, 'sla2': sla2, 'kext': kext, 'rue': rue,
        'q10': q10,
        'ec': ec,
        'frm': frm,
        'particao': [{'fdvs': fdvs[i], 'f0': f[i][0], 'f1': f[i][1],
                      'f2': f[i][2], 'f3': f[i][3]} for i in range(len(fdvs))]
    }

# ============================================================================
# FUNÇÃO DE SIMULAÇÃO
# ============================================================================
def executar_simulacao(meteo_data, params, dia_inicio):
    """Executa o modelo CROPSIM e retorna os dados diários e resumo."""
    TSum1 = params['tsum1']
    TSum2 = params['tsum2']
    Tb    = params['tb']
    MSi   = params['msi']
    IAFi  = params['iafi']
    Vida  = int(params['vida'])      # Garantir inteiro (corrige TypeError)
    SLA1  = params['sla1']
    SLA2  = params['sla2']
    Kext  = params['kext']
    RUE   = params['rue']
    Q10   = params['q10']
    EC    = params['ec']
    fRM   = params['frm']
    FDVS  = [p['fdvs'] for p in params['particao']]
    F     = [[p['f0'], p['f1'], p['f2'], p['f3']] for p in params['particao']]

    Rad  = meteo_data['Rad']
    Tmed = meteo_data['Tmed']

    DVS = 0.0
    Dia = dia_inicio - 1
    NDia = 0
    TSum = 0.0
    IAF = IAFi
    IAFmax = IAFi
    Massa = [MSi * F[0][i] for i in range(4)]

    DeltaIAF = ['']
    DeltaMassaf = ['']

    resultados = {
        'dias': [], 'dvs': [], 'iaf': [],
        'massa_folhas': [], 'massa_raizes': [], 'massa_caule': [], 'massa_sementes': [],
        'massa_total': [], 'cresc_folhas': [], 'morte_idade': [],
        'fotobr': [], 'fotoliq': [], 'rm_total': [], 'radabs': [],
        'rad_inc': [], 'tmed': [], 'delta_iaf': [], 'delta_mf': []
    }

    while DVS <= 2.0 and Dia < len(Tmed) - 1:
        Dia += 1
        NDia += 1

        TSum += max(0.0, Tmed[Dia] - Tb)
        if TSum <= TSum1:
            DVS = TSum / TSum1
        else:
            DVS = 1.0 + (TSum - TSum1) / TSum2

        if DVS < 1.0:
            SLA = SLA1 + (SLA2 - SLA1) * DVS
        else:
            SLA = SLA2

        if DVS >= FDVS[-1]:
            Fdia = F[-1]
        else:
            for d in range(1, len(FDVS)):
                if DVS < FDVS[d]:
                    frac = (DVS - FDVS[d-1]) / (FDVS[d] - FDVS[d-1])
                    Fdia = [F[d-1][i] + frac * (F[d][i] - F[d-1][i]) for i in range(4)]
                    break

        RadAbs = (1.0 - math.exp(-Kext * IAF)) * Rad[Dia]
        FotoBr = RadAbs * RUE * 1e-6 * 1e4

        RM_total = 0.0
        for i in range(4):
            RM = Massa[i] * fRM[i] * (Q10 ** ((Tmed[Dia] - 20.0) / 10.0))
            RM_total += RM

        FotoLiq = max(0.0, FotoBr - RM_total)

        delta_folhas = FotoLiq * Fdia[0] * EC[0]
        delta_raizes = FotoLiq * Fdia[1] * EC[1]
        delta_caule  = FotoLiq * Fdia[2] * EC[2]
        delta_sementes = FotoLiq * Fdia[3] * EC[3]

        for i, delta in enumerate([delta_folhas, delta_raizes, delta_caule, delta_sementes]):
            Massa[i] += delta

        delta_IAF_hoje = SLA * delta_folhas
        delta_Mf_hoje = delta_folhas
        DeltaIAF.append(delta_IAF_hoje)
        DeltaMassaf.append(delta_Mf_hoje)

        morte_hoje = 0.0
        if NDia <= Vida:
            IAF += delta_IAF_hoje
        else:
            IAF += delta_IAF_hoje - DeltaIAF[NDia - Vida]
            Massa[0] -= DeltaMassaf[NDia - Vida]
            morte_hoje = DeltaMassaf[NDia - Vida]

        if IAF > IAFmax:
            IAFmax = IAF

        resultados['dias'].append(Dia + 1)
        resultados['dvs'].append(round(DVS, 4))
        resultados['iaf'].append(round(IAF, 4))
        resultados['massa_folhas'].append(round(Massa[0], 2))
        resultados['massa_raizes'].append(round(Massa[1], 2))
        resultados['massa_caule'].append(round(Massa[2], 2))
        resultados['massa_sementes'].append(round(Massa[3], 2))
        resultados['massa_total'].append(round(sum(Massa), 2))
        resultados['cresc_folhas'].append(round(delta_Mf_hoje, 2))
        resultados['morte_idade'].append(round(morte_hoje, 2))
        resultados['fotobr'].append(round(FotoBr, 2))
        resultados['fotoliq'].append(round(FotoLiq, 2))
        resultados['rm_total'].append(round(RM_total, 2))
        resultados['radabs'].append(round(RadAbs, 2))
        resultados['rad_inc'].append(Rad[Dia])
        resultados['tmed'].append(Tmed[Dia])
        resultados['delta_iaf'].append(round(delta_IAF_hoje, 6))
        resultados['delta_mf'].append(round(delta_Mf_hoje, 4))

    resumo = {
        'iaf_max': round(IAFmax, 3),
        'prod_sementes': round(Massa[3], 1),
        'massa_total': round(sum(Massa), 1),
        'duracao': resultados['dias'][-1] - dia_inicio + 1 if resultados['dias'] else 0,
        'dvs_final': round(DVS, 3)
    }

    return {'resumo': resumo, 'dados': resultados}

# ============================================================================
# FUNÇÃO AUXILIAR PARA PREPARAR PARÂMETROS (usada na sensibilidade)
# ============================================================================
def preparar_params(p):
    """Converte o dicionário recebido do front-end para o formato interno."""
    return {
        'tsum1': p['tsum1'], 'tsum2': p['tsum2'], 'tb': p['tb'],
        'msi': p['msi'], 'iafi': p['iafi'], 'vida': int(p['vida']),
        'sla1': p['sla1'], 'sla2': p['sla2'], 'kext': p['kext'], 'rue': p['rue'],
        'q10': p['q10'],
        'ec': [p['ec']['0'], p['ec']['1'], p['ec']['2'], p['ec']['3']],
        'frm': [p['frm']['0'], p['frm']['1'], p['frm']['2'], p['frm']['3']],
        'particao': sorted(p['particao'], key=lambda x: x['fdvs'])
    }

# ============================================================================
# ROTAS FLASK
# ============================================================================

@app.route('/')
def index():
    """Página principal: lista os arquivos disponíveis."""
    arquivos_meteo = sorted([f for f in os.listdir(WORKDIR) if f.lower().endswith('.met')])
    arquivos_cultura = sorted([f for f in os.listdir(WORKDIR) if f.lower().endswith('.crp')])
    return render_template('index.html',
                           arquivos_meteo=arquivos_meteo,
                           arquivos_cultura=arquivos_cultura)

@app.route('/debug')
def debug():
    """Página de debug para testar as APIs."""
    return render_template('debug.html')

@app.route('/api/arquivos')
def api_arquivos():
    """Retorna listas de arquivos .met e .crp em JSON."""
    meteo = sorted([f for f in os.listdir(WORKDIR) if f.lower().endswith('.met')])
    cultura = sorted([f for f in os.listdir(WORKDIR) if f.lower().endswith('.crp')])
    return jsonify({'met': meteo, 'crp': cultura})

@app.route('/upload', methods=['POST'])
def upload():
    """Recebe um arquivo via upload e salva no diretório de trabalho."""
    if 'arquivo' not in request.files:
        return jsonify({'success': False, 'error': 'Nenhum arquivo enviado'})
    file = request.files['arquivo']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nome do arquivo vazio'})
    if not (file.filename.lower().endswith('.met') or file.filename.lower().endswith('.crp')):
        return jsonify({'success': False, 'error': 'Apenas arquivos .met e .crp são aceitos'})
    caminho = os.path.join(WORKDIR, file.filename)
    file.save(caminho)
    return jsonify({'success': True, 'message': f'Arquivo {file.filename} salvo com sucesso'})

@app.route('/carregar_cultura')
def carregar_cultura():
    """Retorna os parâmetros da cultura em JSON."""
    arquivo = request.args.get('arquivo', '')
    caminho = os.path.join(WORKDIR, arquivo)
    if not os.path.exists(caminho):
        return jsonify({'success': False, 'error': 'Arquivo não encontrado'})
    try:
        cultura = ler_cultura(caminho)
        cultura['ec_dict'] = {
            'folhas': cultura['ec'][0],
            'raizes': cultura['ec'][1],
            'caule': cultura['ec'][2],
            'sementes': cultura['ec'][3]
        }
        cultura['frm_dict'] = {
            'folhas': cultura['frm'][0],
            'raizes': cultura['frm'][1],
            'caule': cultura['frm'][2],
            'sementes': cultura['frm'][3]
        }
        return jsonify({'success': True, 'cultura': cultura})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/simular', methods=['POST'])
def simular():
    """Recebe parâmetros, executa a simulação e retorna resultados."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Dados JSON inválidos'})

    meteo_file = data.get('arquivo_meteo')
    cultura_file = data.get('arquivo_cultura')
    data_inicio_str = data.get('data_inicio')
    params_edit = data.get('parametros_editados')

    if not all([meteo_file, cultura_file, data_inicio_str]):
        return jsonify({'success': False, 'error': 'Parâmetros obrigatórios ausentes'})

    if not params_edit or not params_edit.get('particao') or len(params_edit['particao']) == 0:
        return jsonify({'success': False, 'error': 'Tabela de partição vazia ou não enviada'})

    params_edit['particao'].sort(key=lambda x: x.get('fdvs', 0))

    caminho_meteo = os.path.join(WORKDIR, meteo_file)
    if not os.path.exists(caminho_meteo):
        return jsonify({'success': False, 'error': f'Arquivo meteorológico {meteo_file} não encontrado'})

    try:
        data_dt = datetime.strptime(data_inicio_str, '%Y-%m-%d')
        dia_inicio = data_dt.timetuple().tm_yday
        meteo_data = ler_meteo(caminho_meteo)

        p = params_edit
        params_final = {
            'tsum1': p['tsum1'], 'tsum2': p['tsum2'], 'tb': p['tb'],
            'msi': p['msi'], 'iafi': p['iafi'], 'vida': int(p['vida']),
            'sla1': p['sla1'], 'sla2': p['sla2'], 'kext': p['kext'], 'rue': p['rue'],
            'q10': p['q10'],
            'ec': [p['ec']['0'], p['ec']['1'], p['ec']['2'], p['ec']['3']],
            'frm': [p['frm']['0'], p['frm']['1'], p['frm']['2'], p['frm']['3']],
            'particao': p['particao']
        }

        resultado = executar_simulacao(meteo_data, params_final, dia_inicio)
        return jsonify({'success': True, 'resultados': resultado})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Erro: {str(e)}'})

@app.route('/sensibilidade', methods=['POST'])
def sensibilidade():
    """Análise de sensibilidade com variação configurável."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'Dados JSON inválidos'})

    arquivo_meteo = data.get('arquivo_meteo')
    data_inicio_str = data.get('data_inicio')
    params_base = data.get('parametros_base')
    params_variar = data.get('parametros_variar', [])
    saidas = data.get('saidas', [])
    dP_fraction = data.get('dP_fraction', 0.01)  # fração (ex: 0.01 = 1%)

    if not all([arquivo_meteo, data_inicio_str, params_base, params_variar, saidas]):
        return jsonify({'success': False, 'error': 'Dados incompletos'})

    caminho_meteo = os.path.join(WORKDIR, arquivo_meteo)
    if not os.path.exists(caminho_meteo):
        return jsonify({'success': False, 'error': 'Arquivo meteorológico não encontrado'})

    try:
        data_dt = datetime.strptime(data_inicio_str, '%Y-%m-%d')
        dia_inicio = data_dt.timetuple().tm_yday
        meteo_data = ler_meteo(caminho_meteo)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

    # Preparar parâmetros base
    base_params = preparar_params(params_base)

    # Simulação base
    base_result = executar_simulacao(meteo_data, base_params, dia_inicio)
    base_sementes = base_result['resumo']['prod_sementes']
    base_iafmax = base_result['resumo']['iaf_max']

    resultados_sens = {}

    for param in params_variar:
        # Copiar os parâmetros base
        new_params = json.loads(json.dumps(base_params))

        if param == 'vida':
            new_params['vida'] = base_params['vida'] * (1 + dP_fraction)
        elif param == 'sla1':
            new_params['sla1'] = base_params['sla1'] * (1 + dP_fraction)
        elif param == 'rue':
            new_params['rue'] = base_params['rue'] * (1 + dP_fraction)
        elif param == 'q10':
            new_params['q10'] = base_params['q10'] * (1 + dP_fraction)
        else:
            continue

        res = executar_simulacao(meteo_data, new_params, dia_inicio)
        new_sementes = res['resumo']['prod_sementes']
        new_iafmax = res['resumo']['iaf_max']

        resultados_sens[param] = {}
        if 'sementes' in saidas and base_sementes > 0:
            sens_sem = (new_sementes - base_sementes) / base_sementes / dP_fraction
            resultados_sens[param]['sementes'] = sens_sem
        if 'iafmax' in saidas and base_iafmax > 0:
            sens_iaf = (new_iafmax - base_iafmax) / base_iafmax / dP_fraction
            resultados_sens[param]['iafmax'] = sens_iaf

    return jsonify({'success': True, 'resultados': resultados_sens})

# ============================================================================
# INICIALIZAÇÃO
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port)