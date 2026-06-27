"""Recebe (telefone, texto), interpreta e executa a ação no EmDia, devolvendo a resposta."""
from datetime import date
import llm
import emdia

_PM_LABEL = {"pix": "Pix", "card": "Cartão", "cash": "Dinheiro"}
_PERIODO_LABEL = {"mes_atual": "este mês", "proximo_mes": "próximo mês", "todos": "no total"}


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
    """tipo = 'income' (a receber) ou 'expense' (a pagar)."""
    filtrados = [i for i in items if i.get("type") == tipo and _in_period(i.get("due_date"), period)]
    if not filtrados:
        venc = "" if period == "todos" else f" ({_PERIODO_LABEL.get(period, '')})"
        return (f"✅ Nenhum recebimento em aberto{venc}." if tipo == "income"
                else f"✅ Nenhuma conta a pagar{venc}.")
    filtrados.sort(key=lambda i: i.get("due_date") or "9999")
    titulo = "📥 *Falta receber:*" if tipo == "income" else "📤 *Contas a pagar:*"
    linhas = [titulo, ""]
    total = 0.0
    for i in filtrados:
        total += float(i.get("amount", 0))
        venc = _fmt_date(i.get("due_date"))
        flag = "  ⚠️ _vencido_" if i.get("overdue") else ""
        linhas.append(f"• *{i.get('description', '').strip()}*")
        linhas.append(f"  {_brl(i.get('amount'))} · vence {venc}{flag}")
        linhas.append("")
    linhas.append(f"*Total: {_brl(total)}*")
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
    linhas.append(f"💰 Saldo na conta: *{_brl(s.get('account_balance', 0))}*")
    linhas.append(f"📥 Entradas no mês (recebido): *{_brl(fin.get('received_month', 0))}*")
    linhas.append(f"📤 Saídas no mês (pago): *{_brl(fin.get('paid_month', 0))}*")
    linhas.append(f"⏳ A receber (mês): *{_brl(fin.get('expected_income', 0))}*")
    linhas.append(f"⏳ A pagar (mês): *{_brl(fin.get('bills_to_pay', 0))}*")
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


def handle(phone: str, text: str) -> str | None:
    # GATE: só responde quem está cadastrado (profiles.phone). Caso contrário,
    # retorna None => silêncio total (não chama a IA nem responde no WhatsApp).
    s = emdia.get_summary(phone)
    if not s.get("found"):
        return None

    action = llm.interpret(text)
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
                return f"📥 A receber (próximo mês): *{_brl(_period_total(pending, 'income', 'proximo_mes'))}*"
            recebido = fin.get("received_month", 0)
            a_receber = fin.get("expected_income", 0)
            return (f"📥 *Entradas (este mês)*\n"
                    f"• Já recebido: *{_brl(recebido)}*\n"
                    f"• Ainda a receber: *{_brl(a_receber)}*")
        if consulta == "saidas":
            # SAÍDAS = o que JÁ saiu. Mostra também o que ainda falta pagar.
            if periodo == "proximo_mes":
                return f"📤 A pagar (próximo mês): *{_brl(_period_total(pending, 'expense', 'proximo_mes'))}*"
            pago = fin.get("paid_month", 0)
            a_pagar = fin.get("bills_to_pay", 0)
            return (f"📤 *Saídas (este mês)*\n"
                    f"• Já pago: *{_brl(pago)}*\n"
                    f"• Ainda a pagar: *{_brl(a_pagar)}*")
        if consulta == "a_receber":
            p = periodo or "mes_atual"
            return f"📥 A receber ({_PERIODO_LABEL[p]}): *{_brl(_period_total(pending, 'income', p))}*"
        if consulta == "a_pagar":
            p = periodo or "mes_atual"
            return f"📤 A pagar ({_PERIODO_LABEL[p]}): *{_brl(_period_total(pending, 'expense', p))}*"
        if consulta == "lista_receber":
            return _format_pending_list(pending, "income", periodo or "todos")
        if consulta == "lista_pagar":
            return _format_pending_list(pending, "expense", periodo or "todos")
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

    if a == "definir_saldo":
        bal = action.get("balance")
        if bal is None:
            return "Quanto você tem na conta? Ex.: \"meu saldo é 3000\"."
        r = emdia.set_balance(phone, float(bal))
        if not r.get("success"):
            return "Não encontrei seu cadastro para atualizar o saldo."
        return f"✅ Saldo na conta atualizado para {_brl(r['account_balance'])}."

    if a == "registrar":
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
        verbo = "Receita" if type_ == "income" else "Despesa"
        if status == "pending":
            extra = f" (a {'receber' if type_ == 'income' else 'pagar'})"
            return f"✅ {verbo} de {_brl(amount)} registrada{extra}."
        return f"✅ {verbo} de {_brl(amount)} registrada. Saldo na conta: {_brl(r.get('account_balance', 0))}."

    return (
        "👋 Sou o assistente do EmDia. Você pode dizer:\n"
        "• \"paguei 150 de luz no pix\"\n"
        "• \"recebi 2000 do cliente\"\n"
        "• \"vou pagar 300 de internet dia 10\" (pendente)\n"
        "• \"meu saldo é 3000\"\n"
        "• \"qual meu saldo?\" / \"resumo\""
    )
