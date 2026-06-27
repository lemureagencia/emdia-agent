"""Recebe (telefone, texto), interpreta e executa a ação no EmDia, devolvendo a resposta."""
from datetime import date
import llm
import emdia

_PM_LABEL = {"pix": "Pix", "card": "Cartão", "cash": "Dinheiro"}
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
          "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _month_name(offset: int = 0) -> str:
    """Nome do mês corrente + offset (ex.: 'junho'; 'janeiro/2027' se virar o ano)."""
    today = date.today()
    idx = (today.month - 1) + offset
    y = today.year + idx // 12
    nome = _MESES[idx % 12]
    return nome if y == today.year else f"{nome}/{y}"


def _periodo_label(period: str | None) -> str:
    if period == "mes_atual":
        return _month_name(0)
    if period == "proximo_mes":
        return _month_name(1)
    return "no total"


def _month_str(offset: int) -> str:
    """Retorna 'YYYY-MM' do mês corrente + offset."""
    today = date.today()
    idx = (today.month - 1) + offset
    y = today.year + idx // 12
    m = idx % 12 + 1
    return f"{y:04d}-{m:02d}"


def _in_period(due: str | None, period: str) -> bool:
    if period == "todos":
        return True
    if period == "mes_atual":
        # vence até o fim do mês corrente (inclui vencidos e sem data)
        return (not due) or due[:7] <= _month_str(0)
    if period == "proximo_mes":
        return bool(due) and due[:7] == _month_str(1)
    return True


def _period_total(items: list, tipo: str, period: str) -> float:
    return sum(float(i.get("amount", 0)) for i in items
               if i.get("type") == tipo and _in_period(i.get("due_date"), period))


def _fmt_date(d: str | None) -> str:
    if not d:
        return "sem data"
    try:
        y, m, day = d.split("-")
        return f"{day}/{m}/{y}"
    except ValueError:
        return d


def _format_pending_list(items: list, tipo: str, period: str = "todos") -> str:
    """tipo = 'income' (a receber) ou 'expense' (a pagar).
    Separa em Vencidos e A vencer, para uma única resposta cobrir os dois.
    """
    filtrados = [i for i in items if i.get("type") == tipo and _in_period(i.get("due_date"), period)]
    if not filtrados:
        venc = "" if period == "todos" else f" ({_periodo_label(period)})"
        return (f"✅ Nenhum recebimento em aberto{venc}." if tipo == "income"
                else f"✅ Nenhuma conta a pagar{venc}.")
    filtrados.sort(key=lambda i: i.get("due_date") or "9999")
    titulo = "📥 *Falta receber:*" if tipo == "income" else "📤 *Contas a pagar:*"
    vencidos = [i for i in filtrados if i.get("overdue")]
    a_vencer = [i for i in filtrados if not i.get("overdue")]
    linhas = [titulo, ""]
    total = 0.0

    def _bloco(subtitulo: str | None, grupo: list, venceu: bool) -> None:
        nonlocal total
        if not grupo:
            return
        if subtitulo:
            linhas.append(subtitulo)
        verbo = "venceu" if venceu else "vence"
        for i in grupo:
            total += float(i.get("amount", 0))
            linhas.append(f"• *{i.get('description', '').strip()}*")
            linhas.append(f"  {_brl(i.get('amount'))} · {verbo} {_fmt_date(i.get('due_date'))}")
        linhas.append("")

    # Se houver vencidos, mostra os dois blocos rotulados; senão, lista simples.
    if vencidos:
        _bloco("⚠️ _Vencidos:_", vencidos, venceu=True)
        _bloco("📅 _A vencer:_", a_vencer, venceu=False)
    else:
        _bloco(None, a_vencer, venceu=False)
    linhas.append(f"*Total: {_brl(total)}*")
    return "\n".join(linhas)


def _format_overdue_list(items: list) -> str:
    """Lista os itens VENCIDOS (a receber e a pagar), com nome, valor e data."""
    venc = [i for i in items if i.get("overdue")]
    if not venc:
        return "✅ Nenhuma conta vencida. Tudo em dia! 🎉"
    venc.sort(key=lambda i: i.get("due_date") or "9999")
    receber = [i for i in venc if i.get("type") == "income"]
    pagar = [i for i in venc if i.get("type") == "expense"]
    linhas = ["⚠️ *Vencidos*", ""]
    total = 0.0

    def _bloco(titulo: str, grupo: list) -> None:
        nonlocal total
        if not grupo:
            return
        linhas.append(titulo)
        for i in grupo:
            total += float(i.get("amount", 0))
            linhas.append(f"• *{i.get('description', '').strip()}*")
            linhas.append(f"  {_brl(i.get('amount'))} · venceu {_fmt_date(i.get('due_date'))}")
        linhas.append("")

    _bloco("📥 *Falta receber (vencido):*", receber)
    _bloco("📤 *Contas a pagar (vencido):*", pagar)
    linhas.append(f"*Total vencido: {_brl(total)}*")
    return "\n".join(linhas)


def _brl(v) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def _format_summary(s: dict) -> str:
    fin = s.get("finance", {}) or {}
    nome = (s.get("name") or "").strip()
    linhas = [f"📊 *Resumo{(' — ' + nome) if nome else ''}*", ""]
    mes = _month_name(0)
    linhas.append(f"💰 Saldo na conta: *{_brl(s.get('account_balance', 0))}*")
    linhas.append(f"📥 Entradas de {mes} (recebido): *{_brl(fin.get('received_month', 0))}*")
    linhas.append(f"📤 Saídas de {mes} (pago): *{_brl(fin.get('paid_month', 0))}*")
    linhas.append(f"⏳ A receber ({mes}): *{_brl(fin.get('expected_income', 0))}*")
    linhas.append(f"⏳ A pagar ({mes}): *{_brl(fin.get('bills_to_pay', 0))}*")
    overdue = fin.get("overdue_count", 0)
    if overdue:
        total_venc = float(fin.get("income_overdue", 0)) + float(fin.get("expense_overdue", 0))
        linhas.append(f"⚠️ Vencidos: *{_brl(total_venc)}* ({overdue} em atraso)")
    goals = s.get("goals") or []
    if goals:
        linhas.append("")
        linhas.append("🎯 *Metas:*")
        for g in goals[:5]:
            linhas.append(f"• {g['title']}: {_brl(g['current_amount'])} / {_brl(g['target_amount'])} ({g['progress_percent']}%)")
    return "\n".join(linhas)


def _snapshot_text(s: dict) -> str:
    """Panorama financeiro real do cliente, para o LLM compor a resposta (modo inteligente)."""
    fin = s.get("finance", {}) or {}
    pend = s.get("pending") or []
    goals = s.get("goals") or []
    mes = _month_name(0)
    venc_total = float(fin.get("income_overdue", 0)) + float(fin.get("expense_overdue", 0))
    L = [
        f"Nome do cliente: {(s.get('name') or '').strip() or '(sem nome)'}",
        f"Mês atual: {mes}",
        f"Saldo na conta: {_brl(s.get('account_balance', 0))}",
        f"Entradas já recebidas em {mes}: {_brl(fin.get('received_month', 0))}",
        f"Saídas já pagas em {mes}: {_brl(fin.get('paid_month', 0))}",
        f"A receber que vence em {mes} (pendente): {_brl(fin.get('expected_income', 0))}",
        f"A pagar que vence em {mes} (pendente): {_brl(fin.get('bills_to_pay', 0))}",
        f"Total geral a receber (todas as pendências): {_brl(fin.get('income_pending', 0))}",
        f"Total geral a pagar (todas as pendências): {_brl(fin.get('expense_pending', 0))}",
        f"Total vencido/em atraso: {_brl(venc_total)} ({fin.get('overdue_count', 0)} item(ns))",
    ]

    def _itens(grupo: list) -> list:
        grupo = sorted(grupo, key=lambda x: x.get("due_date") or "9999")[:40]
        if not grupo:
            return ["  (nenhum)"]
        return [f"  - {i.get('description', '').strip()} · {_brl(i.get('amount'))} · "
                f"vence {_fmt_date(i.get('due_date'))}{' · VENCIDO' if i.get('overdue') else ''}"
                for i in grupo]

    receber = [i for i in pend if i.get("type") == "income"]
    pagar = [i for i in pend if i.get("type") == "expense"]
    L += ["", "ITENS A RECEBER (clientes/pendências que ainda faltam te pagar):"] + _itens(receber)
    L += ["", "CONTAS A PAGAR (suas despesas pendentes):"] + _itens(pagar)
    if goals:
        L += ["", "METAS:"]
        for g in goals[:10]:
            L.append(f"  - {g['title']}: {_brl(g['current_amount'])} / {_brl(g['target_amount'])} ({g['progress_percent']}%)")
    return "\n".join(L)


def handle(phone: str, text: str) -> str | None:
    # GATE: só responde quem está cadastrado (profiles.phone). Caso contrário,
    # retorna None => silêncio total (não chama a IA nem responde no WhatsApp).
    s = emdia.get_summary(phone)
    if not s.get("found"):
        return None

    # Memória curta: histórico ANTES de processar a mensagem atual.
    history = emdia.recent_messages(phone)
    action = llm.interpret(text, history)
    a = action.get("action")

    if a in ("registrar", "definir_saldo"):
        # Escrita: caminho estruturado e seguro (valores exatos, sem alucinação).
        reply = _do_action(phone, text, action, s)
    else:
        # Leitura: MODO INTELIGENTE — o LLM compõe a resposta a partir dos dados
        # reais (responde perguntas compostas e variadas). Se falhar (sem API
        # key/erro), cai no modo estruturado como rede de segurança.
        reply = llm.answer(text, history, _snapshot_text(s)) or _answer_structured(s, action)

    if reply:
        emdia.log_message(phone, "user", text)
        emdia.log_message(phone, "assistant", reply)
    return reply


def _answer_structured(s: dict, action: dict) -> str:
    """Rede de segurança: resposta canônica quando o modo inteligente não está disponível."""
    a = action.get("action")

    if a == "consultar":
        fin = s.get("finance", {}) or {}
        pending = s.get("pending") or []
        consulta = action.get("consulta") or "tudo"
        periodo = action.get("periodo")
        if consulta == "saldo":
            return f"💰 Saldo na conta: *{_brl(s.get('account_balance', 0))}*"
        if consulta == "entradas":
            # ENTRADAS = o que JÁ entrou. Mostra também o que ainda falta entrar.
            if periodo == "proximo_mes":
                return f"📥 A receber ({_month_name(1)}): *{_brl(_period_total(pending, 'income', 'proximo_mes'))}*"
            recebido = fin.get("received_month", 0)
            a_receber = fin.get("expected_income", 0)
            return (f"📥 *Entradas de {_month_name(0)}*\n"
                    f"• Já recebido: *{_brl(recebido)}*\n"
                    f"• Ainda a receber: *{_brl(a_receber)}*")
        if consulta == "saidas":
            # SAÍDAS = o que JÁ saiu. Mostra também o que ainda falta pagar.
            if periodo == "proximo_mes":
                return f"📤 A pagar ({_month_name(1)}): *{_brl(_period_total(pending, 'expense', 'proximo_mes'))}*"
            pago = fin.get("paid_month", 0)
            a_pagar = fin.get("bills_to_pay", 0)
            return (f"📤 *Saídas de {_month_name(0)}*\n"
                    f"• Já pago: *{_brl(pago)}*\n"
                    f"• Ainda a pagar: *{_brl(a_pagar)}*")
        if consulta == "a_receber":
            p = periodo or "mes_atual"
            return f"📥 A receber ({_periodo_label(p)}): *{_brl(_period_total(pending, 'income', p))}*"
        if consulta == "a_pagar":
            p = periodo or "mes_atual"
            return f"📤 A pagar ({_periodo_label(p)}): *{_brl(_period_total(pending, 'expense', p))}*"
        if consulta == "lista_receber":
            return _format_pending_list(pending, "income", periodo or "todos")
        if consulta == "lista_pagar":
            return _format_pending_list(pending, "expense", periodo or "todos")
        if consulta == "lista_vencidos":
            return _format_overdue_list(pending)
        if consulta == "vencidos":
            total_venc = float(fin.get("income_overdue", 0)) + float(fin.get("expense_overdue", 0))
            return f"⚠️ Vencidos: *{_brl(total_venc)}* ({fin.get('overdue_count', 0)} em atraso)"
        if consulta == "metas":
            goals = s.get("goals") or []
            if not goals:
                return "Você ainda não tem metas cadastradas."
            linhas = ["🎯 *Metas:*", ""]
            for g in goals[:10]:
                linhas.append(f"• *{g['title']}*: {_brl(g['current_amount'])} / {_brl(g['target_amount'])} ({g['progress_percent']}%)")
            return "\n".join(linhas)
        return _format_summary(s)

    return (
        "👋 Sou o assistente do EmDia. Você pode dizer:\n"
        "• \"paguei 150 de luz no pix\"\n"
        "• \"recebi 2000 do cliente\"\n"
        "• \"vou pagar 300 de internet dia 10\" (pendente)\n"
        "• \"meu saldo é 3000\"\n"
        "• \"qual meu saldo?\" / \"resumo\""
    )


def _do_action(phone: str, text: str, action: dict, s: dict) -> str | None:
    """Escritas: registrar transação e definir saldo (caminho estruturado e seguro)."""
    a = action.get("action")

    if a == "definir_saldo":
        bal = action.get("balance")
        if bal is None:
            return "Quanto você tem na conta? Ex.: \"meu saldo é 3000\"."
        r = emdia.set_balance(phone, float(bal))
        if not r.get("success"):
            return "Não encontrei seu cadastro para atualizar o saldo."
        return f"✅ Saldo na conta atualizado para {_brl(r['account_balance'])}."

    # a == "registrar"
    amount = action.get("amount")
    if not amount:
        return "Não entendi o valor. Ex.: \"paguei 150 de luz\" ou \"recebi 2000 do cliente\"."
    type_ = action.get("type", "expense")
    status = action.get("status", "paid")
    r = emdia.register(
        phone=phone,
        type_=type_,
        amount=float(amount),
        description=action.get("description") or text[:80],
        payment_method=action.get("payment_method"),
        status=status,
        due_date=action.get("due_date"),
    )
    if not r.get("success"):
        return "Não encontrei seu cadastro. Confirme seu número no EmDia."
    verbo = "Entrada" if type_ == "income" else "Saída"
    if status == "pending":
        extra = f" (a {'receber' if type_ == 'income' else 'pagar'})"
        return f"✅ {verbo} de {_brl(amount)} registrada{extra}."
    return f"✅ {verbo} de {_brl(amount)} registrada. Saldo na conta: {_brl(r.get('account_balance', 0))}."
