#!/usr/bin/env python3
"""Vigia externo da FERGO.

Consulta o /ping público de cada sistema de fora da hospedagem deles e avisa o
aparelho do dono (notificação pelo Expo) quando um sistema cai, quando volta e
quando o certificado está perto de vencer. Só biblioteca padrão.

Uso: python3 vigia.py sistemas.json estado.json
Segredo (ambiente): VIGIA_PUSH_TOKENS = códigos de aparelho separados por vírgula.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

FALHAS_PARA_AVISAR = 2      # duas passadas seguidas sem resposta = fora do ar
LEMBRAR_A_CADA_S = 6 * 3600  # continua fora: lembra a cada 6 horas
CERT_DIAS = (7, 3, 1)        # avisa quando faltar 7, 3 e 1 dia
LIMITE_S = 12
EXPO = "https://exp.host/--/api/v2/push/send"


def consultar(url: str) -> tuple[bool, str]:
    """Uma tentativa. Fora do ar = não respondeu, não é 200 ou não é o JSON combinado."""
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "fergo-vigia/1", "Accept": "application/json"})
        with urllib.request.urlopen(pedido, timeout=LIMITE_S) as r:
            corpo = r.read(4096)
            if r.status != 200:
                return False, f"HTTP {r.status}"
        try:
            ok = json.loads(corpo).get("ok") is True
        except (ValueError, AttributeError):
            ok = False
        return (True, "ok") if ok else (False, "resposta fora do combinado")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except ssl.SSLCertVerificationError:
        return False, "certificado inválido"
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        motivo = getattr(e, "reason", e)
        return False, "sem resposta" if isinstance(motivo, (socket.timeout, TimeoutError)) else "sem conexão"


def no_ar(url: str, pausa_s: float = 8.0) -> tuple[bool, str]:
    """Duas tentativas na mesma passada, para um soluço de rede não contar como falha."""
    ok, motivo = consultar(url)
    if ok:
        return ok, motivo
    time.sleep(pausa_s)
    return consultar(url)


def dias_do_certificado(host: str, agora: float) -> int | None:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=LIMITE_S) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            fim = ssl.cert_time_to_seconds(t.getpeercert()["notAfter"])
        return int((fim - agora) // 86400)
    except (OSError, ssl.SSLError, KeyError, ValueError):
        return None


def decidir(sistema: dict, ant: dict, ok: bool, motivo: str, dias_cert: int | None, agora: float) -> tuple[dict, list[dict]]:
    """Regra pura: do estado anterior e do que foi visto agora saem o estado novo e os avisos."""
    novo = {"falhas": 0, "fora_desde": None, "avisado_em": None, "cert_avisado": ant.get("cert_avisado")}
    avisos: list[dict] = []
    nome, sid = sistema["nome"], sistema["id"]

    if ok:
        if ant.get("avisado_em"):
            minutos = max(1, int((agora - (ant.get("fora_desde") or agora)) // 60))
            avisos.append({"sistema": sid, "tipo": "voltou", "titulo": nome, "texto": f"Voltou ao ar. Ficou fora por cerca de {duracao(minutos)}."})
    else:
        falhas = int(ant.get("falhas") or 0) + 1
        novo.update(falhas=falhas, fora_desde=ant.get("fora_desde") or agora, avisado_em=ant.get("avisado_em"))
        if falhas >= FALHAS_PARA_AVISAR and not ant.get("avisado_em"):
            novo["avisado_em"] = agora
            avisos.append({"sistema": sid, "tipo": "fora", "titulo": nome, "texto": f"Fora do ar ({motivo})."})
        elif ant.get("avisado_em") and agora - ant["avisado_em"] >= LEMBRAR_A_CADA_S:
            novo["avisado_em"] = agora
            minutos = int((agora - novo["fora_desde"]) // 60)
            avisos.append({"sistema": sid, "tipo": "fora", "titulo": nome, "texto": f"Continua fora do ar há {duracao(minutos)}."})

    if dias_cert is not None:
        marco = next((d for d in sorted(CERT_DIAS) if dias_cert <= d), None)
        if marco is None:
            novo["cert_avisado"] = None  # renovou: zera para avisar de novo no próximo ciclo
        elif ant.get("cert_avisado") is None or marco < ant["cert_avisado"]:
            novo["cert_avisado"] = marco
            quando = "já venceu" if dias_cert < 0 else "vence hoje" if dias_cert == 0 else "vence amanhã" if dias_cert == 1 else f"vence em {dias_cert} dias"
            avisos.append({"sistema": sid, "tipo": "certificado", "titulo": nome, "texto": f"O certificado do site {quando}."})
    return novo, avisos


def duracao(minutos: int) -> str:
    if minutos < 60:
        return f"{minutos} min"
    h, m = divmod(minutos, 60)
    return f"{h} h" if m == 0 else f"{h} h {m} min"


def enviar(tokens: list[str], avisos: list[dict]) -> bool:
    if not tokens or not avisos:
        return True
    mensagens = [
        {"to": t, "title": a["titulo"], "body": a["texto"], "sound": "default", "priority": "high", "data": {"sistema": a["sistema"], "tipo": "alarme", "vigia": a["tipo"]}}
        for a in avisos for t in tokens
    ]
    pedido = urllib.request.Request(EXPO, data=json.dumps(mensagens).encode(), headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=20) as r:
            resposta = json.loads(r.read())
        erros = [x.get("message", "erro") for x in resposta.get("data", []) if x.get("status") != "ok"]
        for e in erros:
            print(f"::warning::Expo recusou um aviso: {e}")
        return not erros
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"::warning::Não deu para enviar o aviso: {type(e).__name__}")
        return False


def tokens_do_ambiente() -> list[str]:
    bruto = os.environ.get("VIGIA_PUSH_TOKENS", "")
    return [t.strip() for t in bruto.replace("\n", ",").split(",") if t.strip().startswith(("ExponentPushToken[", "ExpoPushToken["))]


def main(caminho_sistemas: str, caminho_estado: str) -> int:
    with open(caminho_sistemas, encoding="utf-8") as f:
        sistemas = json.load(f)
    try:
        with open(caminho_estado, encoding="utf-8") as f:
            estado = json.load(f)
    except (FileNotFoundError, ValueError):
        estado = {}
    agora = time.time()
    hoje = datetime.fromtimestamp(agora, timezone.utc).strftime("%Y-%m-%d")
    ver_cert = estado.get("_cert_dia") != hoje  # certificado: uma leitura por dia
    tokens = tokens_do_ambiente()
    if not tokens:
        print("::warning::Segredo VIGIA_PUSH_TOKENS vazio ou fora do formato: o vigia confere, mas não avisa ninguém.")

    novo_estado: dict = {"_cert_dia": hoje, "_dia": hoje}
    todos: list[dict] = []
    for s in sistemas:
        ok, motivo = no_ar(s["ping"])
        dias = dias_do_certificado(urlparse(s["ping"]).hostname or "", agora) if ver_cert and ok else None
        novo, avisos = decidir(s, estado.get(s["id"], {}), ok, motivo, dias, agora)
        novo_estado[s["id"]] = novo
        todos += avisos
        print(f"{s['nome']}: {'no ar' if ok else 'FORA (' + motivo + ')'}" + (f", certificado {dias} dias" if dias is not None else ""))

    if todos and not enviar(tokens, todos):
        # Não entregou: guarda o estado anterior para tentar de novo na próxima passada.
        for s in sistemas:
            if any(a["sistema"] == s["id"] for a in todos):
                novo_estado[s["id"]] = estado.get(s["id"], {}) | {"falhas": novo_estado[s["id"]]["falhas"], "fora_desde": novo_estado[s["id"]]["fora_desde"]}
    with open(caminho_estado, "w", encoding="utf-8") as f:
        json.dump(novo_estado, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
