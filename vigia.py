#!/usr/bin/env python3
"""Vigia externo da FERGO.

Consulta de fora da hospedagem o /ping de cada sistema, a página de cada site e o
boletim que o servidor publica sobre si mesmo (certificados, backups, disco e
serviços), e avisa o aparelho do dono (notificação pelo Expo) quando algo cai,
quando volta e quando um certificado está perto de vencer. Só biblioteca padrão.

Uso: python3 vigia.py sistemas.json estado.json
Segredo (ambiente): VIGIA_PUSH_TOKENS = códigos de aparelho separados por vírgula.
"""
from __future__ import annotations

import json
import re
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
SAUDE_VELHA_S = 3 * 3600   # boletim do servidor com mais de 3 horas = servidor parou de se conferir
EXPO = "https://exp.host/--/api/v2/push/send"
RECIBOS = "https://exp.host/--/api/v2/push/getReceipts"


def esconder(texto: str) -> str:
    """O registro do GitHub é público: nunca imprime o código do aparelho."""
    return re.sub(r"Expo(nent)?PushToken\[[^\]]*\]", "ExpoPushToken[…]", str(texto))


def ler_saude(corpo: bytes, agora: float) -> tuple[bool, str]:
    """Boletim que o próprio servidor publica: certificados, backups, disco e serviços.
    Boletim velho também é problema: quer dizer que o servidor parou de se conferir."""
    try:
        d = json.loads(corpo)
        gerado = float(d["gerado"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return False, "boletim fora do combinado"
    if agora - gerado > SAUDE_VELHA_S:
        return False, "servidor sem se conferir há " + duracao(int((agora - gerado) // 60))
    if d.get("ok") is True:
        return True, "ok"
    problemas = [str(p)[:40] for p in (d.get("problemas") or []) if isinstance(p, str)][:4]
    return False, ", ".join(problemas) or "problema não informado"


def consultar(url: str, tipo: str = "ping", agora: float | None = None) -> tuple[bool, str]:
    """Uma tentativa. Fora do ar = não respondeu, não é 200 ou não é a resposta combinada.
    tipo "ping": JSON com ok=true. "pagina": basta responder 200. "saude": boletim do servidor."""
    try:
        pedido = urllib.request.Request(url, headers={"User-Agent": "fergo-vigia/1", "Accept": "application/json, text/html;q=0.9"})
        with urllib.request.urlopen(pedido, timeout=LIMITE_S) as r:
            corpo = r.read(4096)
            if r.status != 200:
                return False, f"HTTP {r.status}"
        if tipo == "pagina":
            return True, "ok"
        if tipo == "saude":
            return ler_saude(corpo, time.time() if agora is None else agora)
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


def no_ar(url: str, pausa_s: float = 8.0, tipo: str = "ping") -> tuple[bool, str]:
    """Duas tentativas na mesma passada, para um soluço de rede não contar como falha."""
    ok, motivo = consultar(url, tipo)
    if ok:
        return ok, motivo
    time.sleep(pausa_s)
    return consultar(url, tipo)


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
    saude = sistema.get("tipo") == "saude"

    if ok:
        if ant.get("avisado_em"):
            minutos = max(1, int((agora - (ant.get("fora_desde") or agora)) // 60))
            avisos.append({"sistema": sid, "tipo": "voltou", "titulo": nome, "texto": f"Voltou ao normal depois de {duracao(minutos)}." if saude else f"Voltou ao ar. Ficou fora por cerca de {duracao(minutos)}."})
    else:
        falhas = int(ant.get("falhas") or 0) + 1
        novo.update(falhas=falhas, fora_desde=ant.get("fora_desde") or agora, avisado_em=ant.get("avisado_em"))
        if falhas >= FALHAS_PARA_AVISAR and not ant.get("avisado_em"):
            novo["avisado_em"] = agora
            avisos.append({"sistema": sid, "tipo": "fora", "titulo": nome, "texto": f"Precisa de atenção: {motivo}." if saude else f"Fora do ar ({motivo})."})
        elif ant.get("avisado_em") and agora - ant["avisado_em"] >= LEMBRAR_A_CADA_S:
            novo["avisado_em"] = agora
            minutos = int((agora - novo["fora_desde"]) // 60)
            avisos.append({"sistema": sid, "tipo": "fora", "titulo": nome, "texto": f"Continua precisando de atenção há {duracao(minutos)}: {motivo}." if saude else f"Continua fora do ar há {duracao(minutos)}."})

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
            print(f"::warning::Expo recusou um aviso: {esconder(e)}")
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
        ok, motivo = no_ar(s["ping"], tipo=s.get("tipo", "ping"))
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


def _postar(url: str, corpo: object) -> dict:
    pedido = urllib.request.Request(url, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=20) as r:
        return json.loads(r.read())


def teste() -> int:
    """Manda um aviso de teste e lê o recibo da Apple pelo Expo, para saber se chegou ou por que não."""
    tokens = tokens_do_ambiente()
    if not tokens:
        print("::error::Segredo VIGIA_PUSH_TOKENS vazio ou fora do formato.")
        return 1
    msgs = [{"to": t, "title": "FERGO", "body": "Teste do vigia.", "sound": "default", "priority": "high", "data": {"tipo": "teste"}} for t in tokens]
    tickets = _postar(EXPO, msgs).get("data", [])
    ids = []
    for n, t in enumerate(tickets, 1):
        if t.get("status") == "ok":
            ids.append(t["id"])
            print(f"Aparelho {n}: Expo aceitou o envio.")
        else:
            print(f"::error::Aparelho {n}: Expo recusou: {esconder(t.get('message'))} {t.get('details', {}).get('error', '')}")
    if not ids:
        return 1
    time.sleep(25)
    recibos = _postar(RECIBOS, {"ids": ids}).get("data", {})
    falhou = False
    for n, i in enumerate(ids, 1):
        r = recibos.get(i)
        if r is None:
            print(f"Aparelho {n}: recibo ainda não saiu (a Apple não respondeu em 25 s).")
        elif r.get("status") == "ok":
            print(f"Aparelho {n}: a Apple aceitou. O aviso foi entregue ao iPhone.")
        else:
            falhou = True
            print(f"::error::Aparelho {n}: a Apple recusou: {r.get('details', {}).get('error', '')} {esconder(r.get('message'))}")
    return 1 if falhou else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--teste"]:
        sys.exit(teste())
    sys.exit(main(sys.argv[1], sys.argv[2]))
