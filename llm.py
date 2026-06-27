"""Interpretação da mensagem do usuário em uma AÇÃO estruturada.

Saída (dict):
{
  "action": "registrar" | "consultar" | "definir_saldo" | "ajuda",
  "type": "income" | "expense",          # se registrar
  "amount": float,                        # se registrar / definir_saldo usa "balance"
  "description": str,
  "status": "paid" | "pending",          # default "paid"
  "payment_method": "pix"|"card"|"cash"|None,
  "due_date": "YYYY-MM-DD" | None,
  "balance": float                        # se definir_saldo
}

Provider definido em config.LLM_PROVIDER (rule|openai|gemini|anthropic).
'rule' funciona sem nenhuma API key (bom para testar o fluxo).
"""
import json
import re
from datetime import date
import config

_SYSTEM_BASE = """Você é o assistente financeiro do app EmDia. O usuário fala em português \
sobre dinheiro. Hoje é {hoje}. Interprete a mensagem e responda APENAS com um JSON válido \
(sem texto extra, sem markdown) com o formato:

{{"action": "registrar|consultar|definir_saldo|ajuda",
 "type": "income|expense",
 "amount": number,
 "description": "texto curto",
 "status": "paid|pending",
 "payment_method": "pix|card|cash",
 "due_date": "YYYY-MM-DD",
 "balance": number,
 "consulta": "saldo|entradas|saidas|a_receber|a_pagar|vencidos|lista_vencidos|metas|tudo|lista_receber|lista_pagar",
 "periodo": "mes_atual|proximo_mes|todos"}}

Conceito importante (NÃO confundir):
- ENTRADAS / RECEITAS = dinheiro que JÁ entrou (recebido/pago). "quanto recebi", "minhas entradas/receitas do mês", "quanto entrou".
- A RECEBER / RECEITA ESPERADA = dinheiro pendente que ainda VAI entrar. "quanto tenho a receber", "receita esperada", "quem ainda não pagou".
- SAÍDAS / DESPESAS PAGAS = dinheiro que JÁ saiu (pago). "quanto gastei", "minhas saídas/despesas do mês".
- A PAGAR = contas pendentes que ainda VOU pagar. "quanto tenho a pagar", "contas a pagar".

Regras:
- "paguei", "gastei", "comprei" => action=registrar, type=expense, status=paid.
- "recebi", "entrou", "caiu", "ganhei" => action=registrar, type=income, status=paid.
- "vou pagar", "tenho que pagar", "conta a pagar", "a receber", "vence" => status=pending (e due_date se houver data).
- "saldo", "quanto tenho", "quanto devo", "resumo", "relatório", "como ta" => action=consultar.
- Em consultar, preencha "consulta" com o que foi pedido:
  - "saldo" (saldo na conta).
  - "entradas" => quanto JÁ entrou/recebeu no período: "minhas entradas/receitas", "quanto recebi", "quanto entrou".
  - "saidas" => quanto JÁ saiu/gastou no período: "minhas saídas/despesas pagas", "quanto gastei", "quanto saiu".
  - "a_receber" => total PENDENTE a receber: "receita esperada", "quanto falta receber", "quanto tenho a receber".
  - "a_pagar" => total PENDENTE a pagar: "contas a pagar", "quanto falta pagar".
  - "vencidos" => só o TOTAL vencido/em atraso.
  - "lista_receber" => LISTA de quem te deve / clientes a receber. JÁ separa os Vencidos dos A vencer numa resposta só. Use para: "quais clientes não pagaram", "quem me deve", "quem ainda não pagou", "quais clientes faltam pagar", "lista de recebimentos pendentes". IMPORTANTE: use esta MESMO que a pergunta também cite "vencidos", desde que peça os clientes/o que falta receber — ela já mostra os vencidos destacados.
  - "lista_vencidos" => use APENAS quando quiser os vencidos de TUDO (a receber + a pagar juntos) ou explicitamente "só os vencidos", sem pedir a lista de clientes a receber.
  - "metas", "tudo" (resumo geral / "como tá minha grana").
  - "lista_pagar" => quando pedir a LISTA de contas a pagar: "quais contas tenho que pagar", "o que falta pagar", "lista de contas a pagar".
  - Se pedir só o saldo da conta, use "saldo".
- "periodo": se mencionar "próximo mês"/"mês que vem"/"mês seguinte" => "proximo_mes"; se "este mês"/"mês atual"/"esse mês" => "mes_atual"; se não mencionar tempo, omita (null).
- "meu saldo é/agora é X", "ajusta meu saldo para X" => action=definir_saldo, balance=X.
- forma de pagamento: pix, cartão=card, dinheiro=cash. Se não disser, omita o campo.
- due_date: se mencionar só o dia (ex.: "dia 15"), use o PRÓXIMO mês em que esse dia ainda não passou, com base na data de hoje. Se não houver data, omita o campo.
- Use null (não a string "null") para campos sem valor, ou simplesmente omita-os.
- Não invente valores. Se não entender, action=ajuda.

CONTEXTO / HISTÓRICO:
- As mensagens anteriores da conversa são fornecidas. Use-as para entender perguntas curtas de continuação.
- Ex.: se a última pergunta foi sobre "próximo mês" e o usuário diz só "e a receber?", responda consulta=a_receber com periodo=proximo_mes (herda o período do contexto).
- Se o usuário CORRIGIR o período (ex.: "me refiro ao próximo mês", "era pro mês que vem"), REFAÇA a última consulta com o novo período, mantendo o mesmo tipo de consulta da pergunta anterior.
- Se a continuação não tiver contexto claro, trate como pergunta nova normalmente.
Responda só o JSON."""


def _system_prompt() -> str:
    return _SYSTEM_BASE.format(hoje=date.today().isoformat())


_VALID_PM = {"pix", "card", "cash"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean(v):
    """Converte 'null'/'none'/'' em None."""
    if isinstance(v, str) and v.strip().lower() in ("null", "none", ""):
        return None
    return v


def _sanitize(d: dict) -> dict:
    if not isinstance(d, dict):
        return {"action": "ajuda"}
    out = {k: _clean(v) for k, v in d.items()}
    pm = out.get("payment_method")
    out["payment_method"] = pm if pm in _VALID_PM else None
    dd = out.get("due_date")
    out["due_date"] = dd if (isinstance(dd, str) and _DATE_RE.match(dd)) else None
    for num in ("amount", "balance"):
        if out.get(num) is not None:
            try:
                out[num] = float(out[num])
            except (TypeError, ValueError):
                out[num] = None
    return out


# ---------------------------------------------------------------- rule-based
_NUM_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)")


def _parse_amount(text: str) -> float | None:
    m = _NUM_RE.search(text.replace("R$", " "))
    if not m:
        return None
    raw = m.group(1)
    if "." in raw and "," in raw:        # 2.000,50 -> milhar . / decimal ,
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:                      # 150,50 -> decimal ,
        raw = raw.replace(",", ".")
    elif re.match(r"^\d+\.\d{3}$", raw):  # 2.000 -> milhar
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _rule_interpret(text: str) -> dict:
    t = text.lower()
    pm = "pix" if "pix" in t else "card" if ("cartao" in t or "cartão" in t) else "cash" if "dinheiro" in t else None

    consulta_gate = any(k in t for k in [
        "saldo", "quanto tenho", "quanto devo", "quanto recebi", "quanto entrou",
        "quanto gastei", "quanto saiu", "resumo", "relatorio", "relatório",
        "como estou", "como ta", "grana", "a receber", "a pagar", "receita",
        "entrada", "despesa", "saida", "saída", "metas", "vencid",
        "clientes", "me deve", "pagaram", "pagou", "atrasad", "em atraso", "venceu",
    ])
    if consulta_gate:
        if any(k in t for k in ["meu saldo é", "meu saldo e ", "ajusta", "saldo para", "saldo agora", "saldo hoje é"]):
            bal = _parse_amount(t)
            if bal is not None:
                return {"action": "definir_saldo", "balance": bal}
        if any(k in t for k in ["quais", "quem", "lista", "clientes", "nao pagaram", "não pagaram", "nao pagou", "não pagou", "me deve"]):
            # Intenção de "quem te deve" (a receber) vence: a lista já destaca os vencidos.
            if any(k in t for k in ["cliente", "me deve", "nao pagaram", "não pagaram",
                                    "nao pagou", "não pagou", "faltam pagar", "falta pagar", "receber"]):
                consulta = "lista_receber"
            elif "a pagar" in t or "boleto" in t or "fornecedor" in t or "conta" in t:
                consulta = "lista_pagar"
            elif "vencid" in t or "atrasad" in t or "em atraso" in t or "venceu" in t:
                consulta = "lista_vencidos"
            else:
                consulta = "lista_receber"
        elif "resumo" in t or "relat" in t or "grana" in t or "como" in t:
            consulta = "tudo"
        # PENDENTE (ainda vai entrar/sair) — checar antes de entradas/saídas já realizadas
        elif "a receber" in t or "esperad" in t or "falta receber" in t:
            consulta = "a_receber"
        elif "a pagar" in t or "falta pagar" in t or "contas a pagar" in t:
            consulta = "a_pagar"
        elif "vencid" in t or "atrasad" in t:
            consulta = "vencidos"
        # JÁ REALIZADO (já entrou/saiu)
        elif any(k in t for k in ["entrada", "receita", "quanto recebi", "quanto entrou"]):
            consulta = "entradas"
        elif any(k in t for k in ["saida", "saída", "despesa", "quanto gastei", "quanto saiu"]):
            consulta = "saidas"
        elif "pagar" in t or "devo" in t:
            consulta = "a_pagar"
        elif "receber" in t:
            consulta = "a_receber"
        elif "meta" in t:
            consulta = "metas"
        elif "saldo" in t or "conta" in t:
            consulta = "saldo"
        else:
            consulta = "tudo"
        if "proximo mes" in t or "próximo mês" in t or "mes que vem" in t or "mês que vem" in t or "mes seguinte" in t:
            periodo = "proximo_mes"
        elif "este mes" in t or "este mês" in t or "mes atual" in t or "mês atual" in t or "esse mes" in t or "esse mês" in t:
            periodo = "mes_atual"
        else:
            periodo = None
        return {"action": "consultar", "consulta": consulta, "periodo": periodo}

    amount = _parse_amount(t)
    is_expense = any(k in t for k in ["paguei", "gastei", "comprei", "pagar", "despesa", "conta de", "boleto"])
    is_income = any(k in t for k in ["recebi", "entrou", "caiu", "ganhei", "receita", "vendi"])
    if amount is not None and (is_expense or is_income):
        pending = any(k in t for k in ["vou pagar", "tenho que pagar", "a pagar", "a receber", "vence", "vencimento"])
        return {
            "action": "registrar",
            "type": "expense" if is_expense and not is_income else "income",
            "amount": amount,
            "description": text.strip()[:80],
            "status": "pending" if pending else "paid",
            "payment_method": pm,
            "due_date": None,
        }
    return {"action": "ajuda"}


# ---------------------------------------------------------------- LLM providers
def _extract_json(s: str) -> dict:
    s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("sem JSON")


def _history_msgs(history: list | None) -> list:
    """Converte o histórico do banco em mensagens role/content válidas."""
    out = []
    for h in (history or []):
        role = h.get("role")
        content = h.get("content")
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": str(content)})
    return out


def _openai_compat_interpret(text: str, history: list | None, base_url: str | None, default_model: str) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=config.LLM_API_KEY, base_url=base_url) if base_url else OpenAI(api_key=config.LLM_API_KEY)
    messages = [{"role": "system", "content": _system_prompt()}]
    messages += _history_msgs(history)
    messages.append({"role": "user", "content": text})
    r = client.chat.completions.create(
        model=config.LLM_MODEL or default_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(r.choices[0].message.content)


def _openai_interpret(text: str, history: list | None = None) -> dict:
    return _openai_compat_interpret(text, history, None, "gpt-4o-mini")


def _groq_interpret(text: str, history: list | None = None) -> dict:
    # Groq é compatível com a API da OpenAI — reusa o SDK apontando o base_url.
    return _openai_compat_interpret(text, history, "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")


def _gemini_interpret(text: str, history: list | None = None) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=config.LLM_API_KEY)
    model = genai.GenerativeModel(config.LLM_MODEL or "gemini-1.5-flash", system_instruction=_system_prompt())
    chat_hist = [{"role": ("model" if h["role"] == "assistant" else "user"), "parts": [h["content"]]}
                 for h in _history_msgs(history)]
    chat = model.start_chat(history=chat_hist)
    r = chat.send_message(text, generation_config={"response_mime_type": "application/json", "temperature": 0})
    return _extract_json(r.text)


def _anthropic_interpret(text: str, history: list | None = None) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=config.LLM_API_KEY)
    messages = _history_msgs(history) + [{"role": "user", "content": text}]
    r = client.messages.create(
        model=config.LLM_MODEL or "claude-haiku-4-5-20251001",
        max_tokens=300,
        system=_system_prompt(),
        messages=messages,
    )
    return _extract_json(r.content[0].text)


_PROVIDERS = {
    "openai": _openai_interpret,
    "groq": _groq_interpret,
    "gemini": _gemini_interpret,
    "anthropic": _anthropic_interpret,
}


def interpret(text: str, history: list | None = None) -> dict:
    fn = _PROVIDERS.get(config.LLM_PROVIDER)
    if fn:
        try:
            return _sanitize(fn(text, history))
        except Exception as e:  # noqa: BLE001
            print(f"[llm:{config.LLM_PROVIDER}:erro] {e} — caindo no parser por regras")
    return _rule_interpret(text)
