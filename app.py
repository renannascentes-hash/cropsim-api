"""
CropSim Web - API de Produção (sem templates)
Simulação de crescimento de milho (CROPSIM simplificado)
"""

import os
import math
import json
import traceback
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# ============================================================================
# CONFIGURAÇÃO
# ============================================================================
app = Flask(__name__)
CORS(app)

WORKDIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(WORKDIR, exist_ok=True)

# ============================================================================
# FUNÇÕES DE LEITURA
# ============================================================================
def ler_meteo(caminho):
    with open(caminho, 'r', encoding='latin-1') as f:
        linhas = f.read().splitlines()

    Rad, Tmin, Tmax, Vap, Vento, Chuva, Tmed = [], [], [], [], [], [], []
    for i in range(4, 369):
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
    with open(caminho, 'r', encoding='latin-1') as f:
        linhas = f.read().splitlines()

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
        'ec': [float(linhas[i].split()[0]) for i in range(57, 61)],
        'frm': [float(linhas[i].split()[0]) for i in range(65, 69)],
        'particao': [
            {
                'fdvs': float(linhas[i].split()[0]),
                'f0': float(linhas[i].split()[1]),
                'f1': float(linhas[i].split()[2]),
                'f2': float(linhas[i].split()[3]),
                'f3': float(linhas[i].split()[4])
            } for i in range(74, 81)
        ]
    }

# ============================================================================
# SIMULAÇÃO
# ============================================================================
def executar_simulacao(meteo_data, params, dia_inicio):
    TSum1, TSum2, Tb = params['tsum1'], params['tsum2'], params['tb']
    MSi, IAFi, Vida = params['msi'], params['iafi'], int(params['vida'])
    SLA1, SLA2 = params['sla1'], params['sla2']
    Kext, RUE = params['kext'], params['rue']
    Q10 = params['q10']
    EC = params['ec']
    fRM = params['frm']
    FDVS = [p['fdvs'] for p in params['particao']]
    F = [[p['f0'], p['f1'], p['f2'], p['f3']] for p in params['particao']]

    Rad = meteo_data['Rad']
    Tmed = meteo_data['Tmed']

    DVS, Dia, NDia, TSum = 0.0, dia_inicio - 1, 0, 0.0
    IAF, IAFmax = IAFi, IAFi
    Massa = [MSi * F[0][i] for i in range(4)]

    DeltaIAF = ['']
    DeltaMassaf = ['']

    resultados = {'dias': [], 'iaf': [], 'massa_total': []}

    while DVS <= 2.0 and Dia < len(Tmed) - 1:
        Dia += 1
        NDia += 1

        TSum += max(0.0, Tmed[Dia] - Tb)
        DVS = TSum / TSum1 if TSum <= TSum1 else 1 + (TSum - TSum1) / TSum2

        SLA = SLA1 + (SLA2 - SLA1) * min(DVS, 1.0)

        if DVS >= FDVS[-1]:
            Fdia = F[-1]
        else:
            for d in range(1, len(FDVS)):
                if DVS < FDVS[d]:
                    frac = (DVS - FDVS[d-1]) / (FDVS[d] - FDVS[d-1])
                    Fdia = [F[d-1][i] + frac * (F[d][i] - F[d-1][i]) for i in range(4)]
                    break

        RadAbs = (1.0 - math.exp(-Kext * IAF)) * Rad[Dia]
        FotoBr = RadAbs * RUE * 1e-2
        RM_total = sum(Massa[i] * fRM[i] * (Q10 ** ((Tmed[Dia] - 20.0) / 10.0)) for i in range(4))
        FotoLiq = max(0.0, FotoBr - RM_total)

        deltas = [FotoLiq * Fdia[i] * EC[i] for i in range(4)]
        for i in range(4):
            Massa[i] += deltas[i]

        delta_IAF = SLA * deltas[0]
        DeltaIAF.append(delta_IAF)
        DeltaMassaf.append(deltas[0])

        if NDia <= Vida:
            IAF += delta_IAF
        else:
            IAF += delta_IAF - DeltaIAF[NDia - Vida]
            Massa[0] -= DeltaMassaf[NDia - Vida]

        IAFmax = max(IAFmax, IAF)

        resultados['dias'].append(Dia + 1)
        resultados['iaf'].append(round(IAF, 3))
        resultados['massa_total'].append(round(sum(Massa), 2))

    return {
        'resumo': {
            'iaf_max': round(IAFmax, 3),
            'prod_sementes': round(Massa[3], 1),
            'massa_total': round(sum(Massa), 1)
        },
        'dados': resultados
    }

# ============================================================================
# ROTAS API
# ============================================================================

@app.route('/')
def status():
    return jsonify({
        "status": "online",
        "service": "CropSim API",
        "endpoints": ["/api/arquivos", "/simular", "/sensibilidade"]
    })

@app.route('/api/arquivos')
def api_arquivos():
    met = [f for f in os.listdir(WORKDIR) if f.endswith('.met')]
    crp = [f for f in os.listdir(WORKDIR) if f.endswith('.crp')]
    return jsonify({'met': met, 'crp': crp})

@app.route('/simular', methods=['POST'])
def simular():
    data = request.get_json()

    meteo = ler_meteo(os.path.join(WORKDIR, data['arquivo_meteo']))
    params = data['parametros']
    dia_inicio = datetime.strptime(data['data_inicio'], '%Y-%m-%d').timetuple().tm_yday

    resultado = executar_simulacao(meteo, params, dia_inicio)
    return jsonify(resultado)

# ============================================================================
# RUN
# ============================================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)