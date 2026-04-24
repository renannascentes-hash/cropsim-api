import os
import math
import json
import traceback
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

WORKDIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(WORKDIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'met', 'crp'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================================================================
# LEITURA DE ARQUIVOS (igual ao seu, mas adaptado)
# ============================================================================
def ler_meteo(caminho):
    with open(caminho, 'r', encoding='latin-1') as f:
        linhas = f.read().splitlines()
    Rad, Tmin, Tmax, Vap, Vento, Chuva, Tmed = [], [], [], [], [], [], []
    for i in range(4, 369):  # assumindo 365 dias
        a = linhas[i].split()
        Rad.append(float(a[3]))
        Tmin.append(float(a[4]))
        Tmax.append(float(a[5]))
        Vap.append(float(a[6]))
        Vento.append(float(a[7]))
        Chuva.append(float(a[8]))
        Tmed.append((Tmin[-1] + Tmax[-1]) / 2)
    return {'Rad': Rad, 'Tmin': Tmin, 'Tmax': Tmax,
            'Vap': Vap, 'Vento': Vento, 'Chuva': Chuva, 'Tmed': Tmed}

def ler_cultura(caminho):
    with open(caminho, 'r', encoding='latin-1') as f:
        linhas = f.read().splitlines()
    ec = [float(linhas[i].split()[0]) for i in range(57, 61)]
    frm = [float(linhas[i].split()[0]) for i in range(65, 69)]
    particao = []
    for i in range(74, 81):
        partes = linhas[i].split()
        particao.append({
            'fdvs': float(partes[0]),
            'f0': float(partes[1]),
            'f1': float(partes[2]),
            'f2': float(partes[3]),
            'f3': float(partes[4])
        })
    return {
        'tsum1': float(linhas[16].split()[0]),
        'tsum2': float(linhas[17].split()[0]),
        'tb': float(linhas[18].split()[0]),
        'msi': float(linhas[22].split()[0]),
        'iafi': float(linhas[23].split()[0]),
        'vida': int(float(linhas[27].split()[0])),
        'sla1': float(linhas[28].split()[0]),
        'sla2': float(linhas[29].split()[0]),
        'kext': float(linhas[33].split()[0]),
        'rue': float(linhas[34].split()[0]),
        'q10': float(linhas[64].split()[0]),
        'ec': ec,
        'frm': frm,
        'particao': particao,
        # Para facilitar a edição no frontend, crio dicionários também
        'ec_dict': {'folhas': ec[0], 'raizes': ec[1], 'caule': ec[2], 'sementes': ec[3]},
        'frm_dict': {'folhas': frm[0], 'raizes': frm[1], 'caule': frm[2], 'sementes': frm[3]}
    }

# ============================================================================
# SIMULAÇÃO COMPLETA (retorna TUDO que o frontend espera)
# ============================================================================
def executar_simulacao_completa(meteo_data, params, dia_inicio):
    # Extrair parâmetros
    TSum1, TSum2, Tb = params['tsum1'], params['tsum2'], params['tb']
    MSi, IAFi, Vida = params['msi'], params['iafi'], int(params['vida'])
    SLA1, SLA2 = params['sla1'], params['sla2']
    Kext, RUE = params['kext'], params['rue']
    Q10 = params['q10']
    EC = params['ec'] if isinstance(params['ec'], list) else [params['ec'][i] for i in range(4)]
    fRM = params['frm'] if isinstance(params['frm'], list) else [params['frm'][i] for i in range(4)]
    # Tabela de partição
    FDVS = [p['fdvs'] for p in params['particao']]
    F = [[p['f0'], p['f1'], p['f2'], p['f3']] for p in params['particao']]

    Rad = meteo_data['Rad']
    Tmed = meteo_data['Tmed']

    # Inicializações
    DVS = 0.0
    Dia = dia_inicio - 1  # índice do dia (0-based)
    TSum = 0.0
    IAF = IAFi
    IAFmax = IAFi
    Massa = [MSi * F[0][i] for i in range(4)]  # folhas, raízes, caule, sementes

    # Históricos (listas vazias)
    dias_list = []
    dvs_list = []
    iaf_list = []
    massa_folhas_list = []
    massa_raizes_list = []
    massa_caule_list = []
    massa_sementes_list = []
    massa_total_list = []
    fotobr_list = []
    fotoliq_list = []
    rm_total_list = []
    rad_inc_list = []
    radabs_list = []
    tmed_list = []
    cresc_folhas_list = []
    morte_idade_list = []
    delta_iaf_list = []

    # Controle para senescência
    historico_delta_IAF = []  # guarda delta_IAF dos últimos dias
    historico_delta_folhas = []  # guarda delta de massa folhas

    while DVS <= 2.0 and Dia < len(Rad) - 1:
        Dia += 1
        dias_list.append(Dia + 1)  # 1-based
        tmed = Tmed[Dia]
        rad_inc = Rad[Dia]

        # Acúmulo térmico e DVS
        TSum += max(0.0, tmed - Tb)
        if TSum <= TSum1:
            DVS = TSum / TSum1
        else:
            DVS = 1.0 + (TSum - TSum1) / TSum2
        dvs_list.append(round(DVS, 4))

        # SLA
        SLA = SLA1 + (SLA2 - SLA1) * min(DVS, 1.0)

        # Frações de partição no DVS atual
        if DVS >= FDVS[-1]:
            Fdia = F[-1]
        else:
            for idx in range(1, len(FDVS)):
                if DVS < FDVS[idx]:
                    frac = (DVS - FDVS[idx-1]) / (FDVS[idx] - FDVS[idx-1])
                    Fdia = [F[idx-1][i] + frac * (F[idx][i] - F[idx-1][i]) for i in range(4)]
                    break

        # Radiação absorvida
        rad_abs = (1.0 - math.exp(-Kext * IAF)) * rad_inc
        rad_abs_kJ = rad_abs  # kJ/m²/dia

        # Fotossíntese bruta (RUE já em g/MJ -> converter kJ para MJ /10? Cuidado)
        # RUE em g/MJ, rad_abs em kJ/m² => MJ = kJ/1000 => FotoBr = rad_abs/1000 * RUE * 10??
        # Na verdade, g/MJ * MJ/m² = g/m². Para kg/ha: g/m² * 10 = kg/ha.
        # Vamos padronizar: rad_abs/1000 * RUE * 10 = kg/ha/dia.
        fotobr = (rad_abs / 1000.0) * RUE * 10.0   # kg/ha/dia

        # Respiração de manutenção (kg/ha/dia)
        rm_total = 0.0
        for i in range(4):
            rm_total += Massa[i] * fRM[i] * (Q10 ** ((tmed - 20.0) / 10.0))

        # Fotossíntese líquida
        fotoliq = max(0.0, fotobr - rm_total)

        # Incrementos de massa por órgão
        deltas = [fotoliq * Fdia[i] * EC[i] for i in range(4)]
        for i in range(4):
            Massa[i] += deltas[i]

        # Crescimento foliar (kg/ha) e IAF
        delta_massa_folhas = deltas[0]   # incremento de folhas (kg/ha)
        delta_IAF = SLA * delta_massa_folhas
        historico_delta_IAF.append(delta_IAF)
        historico_delta_folhas.append(delta_massa_folhas)

        # Senescência por idade
        if len(historico_delta_IAF) > Vida:
            IAF += delta_IAF - historico_delta_IAF[-Vida]
            Massa[0] -= historico_delta_folhas[-Vida]
            morte_hoje = historico_delta_folhas[-Vida]
        else:
            IAF += delta_IAF
            morte_hoje = 0.0

        IAF = max(0.0, IAF)
        IAFmax = max(IAFmax, IAF)

        # Armazenar resultados
        iaf_list.append(round(IAF, 3))
        massa_folhas_list.append(round(Massa[0], 2))
        massa_raizes_list.append(round(Massa[1], 2))
        massa_caule_list.append(round(Massa[2], 2))
        massa_sementes_list.append(round(Massa[3], 2))
        massa_total_list.append(round(sum(Massa), 2))
        fotobr_list.append(round(fotobr, 2))
        fotoliq_list.append(round(fotoliq, 2))
        rm_total_list.append(round(rm_total, 2))
        rad_inc_list.append(round(rad_inc, 2))
        radabs_list.append(round(rad_abs, 2))
        tmed_list.append(round(tmed, 2))
        cresc_folhas_list.append(round(delta_massa_folhas, 2))
        morte_idade_list.append(round(morte_hoje, 2))
        delta_iaf_list.append(round(delta_IAF, 4))

    # Resumo
    resumo = {
        'iaf_max': round(IAFmax, 3),
        'prod_sementes': round(Massa[3], 1),
        'massa_total': round(sum(Massa), 1),
        'dvs_final': round(DVS, 3),
        'duracao': len(dias_list)
    }

    return {
        'resumo': resumo,
        'dados': {
            'dias': dias_list,
            'dvs': dvs_list,
            'iaf': iaf_list,
            'massa_folhas': massa_folhas_list,
            'massa_raizes': massa_raizes_list,
            'massa_caule': massa_caule_list,
            'massa_sementes': massa_sementes_list,
            'massa_total': massa_total_list,
            'fotobr': fotobr_list,
            'fotoliq': fotoliq_list,
            'rm_total': rm_total_list,
            'rad_inc': rad_inc_list,
            'radabs': radabs_list,
            'tmed': tmed_list,
            'cresc_folhas': cresc_folhas_list,
            'morte_idade': morte_idade_list,
            'delta_iaf': delta_iaf_list
        }
    }

# ============================================================================
# ROTAS DA API
# ============================================================================

@app.route('/')
def status():
    return jsonify({
        "status": "online",
        "service": "CropSim API",
        "endpoints": ["/api/arquivos", "/carregar_cultura", "/simular", "/upload", "/sensibilidade"]
    })

@app.route('/api/arquivos')
def api_arquivos():
    met = [f for f in os.listdir(WORKDIR) if f.endswith('.met')]
    crp = [f for f in os.listdir(WORKDIR) if f.endswith('.crp')]
    # ATENÇÃO: o frontend espera 'arquivos_meteo' e 'arquivos_cultura'
    return jsonify({
        'arquivos_meteo': met,
        'arquivos_cultura': crp
    })

@app.route('/carregar_cultura')
def carregar_cultura():
    arquivo = request.args.get('arquivo')
    if not arquivo:
        return jsonify({'success': False, 'error': 'Nome do arquivo não fornecido'}), 400
    caminho = os.path.join(WORKDIR, arquivo)
    if not os.path.exists(caminho):
        return jsonify({'success': False, 'error': 'Arquivo não encontrado'}), 404
    try:
        cultura = ler_cultura(caminho)
        return jsonify({'success': True, 'cultura': cultura})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload():
    if 'arquivo' not in request.files:
        return jsonify({'success': False, 'error': 'Nenhum arquivo enviado'}), 400
    file = request.files['arquivo']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Nome de arquivo vazio'}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Tipo de arquivo não permitido. Use .met ou .crp'}), 400
    filename = secure_filename(file.filename)
    file.save(os.path.join(WORKDIR, filename))
    return jsonify({'success': True, 'message': f'Arquivo {filename} carregado com sucesso'})

@app.route('/simular', methods=['POST'])
def simular():
    data = request.get_json()
    try:
        arquivo_meteo = data['arquivo_meteo']
        arquivo_cultura = data['arquivo_cultura']
        data_inicio_str = data['data_inicio']
        parametros = data['parametros_editados']

        # Converter data para dia juliano
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
        dia_inicio = data_inicio.timetuple().tm_yday

        # Carregar dados meteorológicos
        meteo = ler_meteo(os.path.join(WORKDIR, arquivo_meteo))

        # Ajustar os parâmetros para o formato esperado pela simulação
        # O frontend envia 'ec' e 'frm' como objetos, precisamos converter em listas
        # Também garante que 'particao' está na mesma estrutura
        params_sim = parametros.copy()
        if isinstance(params_sim.get('ec'), dict):
            params_sim['ec'] = [params_sim['ec'][str(i)] for i in range(4)]  # ou [ec['0'], ec['1'], ...]
        if isinstance(params_sim.get('frm'), dict):
            params_sim['frm'] = [params_sim['frm'][str(i)] for i in range(4)]

        resultado = executar_simulacao_completa(meteo, params_sim, dia_inicio)
        return jsonify({'success': True, 'resultados': resultado})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/sensibilidade', methods=['POST'])
def sensibilidade():
    """
    Executa análise de sensibilidade variando um parâmetro por vez.
    Espera JSON com:
        arquivo_meteo, arquivo_cultura, data_inicio,
        parametros_base, parametros_variar (lista de strings), saidas (lista), dP_fraction
    Retorna dicionário com sensibilidades.
    """
    data = request.get_json()
    try:
        arquivo_meteo = data['arquivo_meteo']
        arquivo_cultura = data['arquivo_cultura']
        data_inicio_str = data['data_inicio']
        params_base = data['parametros_base']
        params_to_vary = data['parametros_variar']   # ex: ['vida', 'rue']
        outputs = data['saidas']                    # ex: ['sementes', 'iafmax']
        dP_fraction = data.get('dP_fraction', 0.01) # fração de variação (ex: 0.01 = 1%)

        # Converter data
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
        dia_inicio = data_inicio.timetuple().tm_yday

        # Carregar meteorologia
        meteo = ler_meteo(os.path.join(WORKDIR, arquivo_meteo))

        # Função para executar simulação com um dicionário de parâmetros
        def run_sim(params):
            # converte ec/frm se necessário
            params_sim = params.copy()
            if isinstance(params_sim.get('ec'), dict):
                params_sim['ec'] = [params_sim['ec'][str(i)] for i in range(4)]
            if isinstance(params_sim.get('frm'), dict):
                params_sim['frm'] = [params_sim['frm'][str(i)] for i in range(4)]
            res = executar_simulacao_completa(meteo, params_sim, dia_inicio)
            return res['resumo']

        # Rodar simulação base
        base_resumo = run_sim(params_base)
        base_values = {}
        if 'sementes' in outputs:
            base_values['sementes'] = base_resumo['prod_sementes']
        if 'iafmax' in outputs:
            base_values['iafmax'] = base_resumo['iaf_max']

        resultados_sens = {}
        for param_name in params_to_vary:
            # Varia o parâmetro em +dP_fraction
            params_var = params_base.copy()
            original_value = params_base[param_name]
            if isinstance(original_value, (int, float)):
                params_var[param_name] = original_value * (1 + dP_fraction)
            else:
                continue  # não suporta variação

            var_resumo = run_sim(params_var)
            resultados_sens[param_name] = {}
            for out in outputs:
                if out == 'sementes':
                    R_base = base_values['sementes']
                    R_var = var_resumo['prod_sementes']
                elif out == 'iafmax':
                    R_base = base_values['iafmax']
                    R_var = var_resumo['iaf_max']
                else:
                    continue
                # Sensibilidade S = (ΔR/R) / (ΔP/P)
                delta_R = R_var - R_base
                if R_base != 0:
                    sens = (delta_R / R_base) / dP_fraction
                else:
                    sens = 0.0
                resultados_sens[param_name][out] = sens

        return jsonify({'success': True, 'resultados': resultados_sens})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# INICIALIZAÇÃO
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
