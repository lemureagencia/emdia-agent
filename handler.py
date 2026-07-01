"""Recebe (telefone, texto), interpreta e executa a ação no EmDia, devolvendo a resposta."""
from datetime import date
import re
import llm
import emdia


def _fix_spacing(text: str) -> str:
    """Garante no máximo 1 linha em branco entre blocos (LLMs tendem a usar 2+)."""
    return re.sub(r'\n{3,}', '\n\n', text).strip()


# ---------------------------------------------------------------- confirmação
_YES_WORDS = {
    "sim", "s", "isso", "confirmo", "confirma", "confirmar", "pode", "ok", "okay",
    "claro", "positivo", "exato", "aham", "yes", "quero", "manda", "bora", "beleza",
    "blz", "certo", "perfeito", "👍", "✅", "isso mesmo", "pode sim", "com certeza",
    "pode ser", "vai", "faz", "fazer", "uhum",
}
_NO_WORDS = {
    "nao", "não", "n", "cancela", "cancelar", "cancele", "deixa", "esquece",
    "negativo", "para", "pare", "nem", "errado", "❌", "deixa pra la", "deixa pra lá",
    "nao quero", "não quero", "melhor nao", "melhor não",
}


def _norm_reply(text: str) -> str:
    """Normaliza para casar sim/não: minúsculo, sem pontuação nas bordas."""
    return re.sub(r'[^\wçãõáéíóúâêô👍✅❌ ]', '', text.strip().lower()).strip()


def _is_yes(text: str) -> bool:
    t = _norm_reply(text)
    if not t or len(t.split()) > 4:
        return False
    return t in _YES_WORDS or t.split()[0] in _YES_WORDS


def _is_no(text: str) -> bool:
    t = _norm_reply(text)
    if not t or len(t.split()) > 4:
        return False
    return t in _NO_WORDS or t.split()[0] in _NO_WORDS


def _side_label(type_: str) -> str:
    return "a receber" if type_ == "income" else "a pagar"


def _item_line(item: dict) -> str:
    """Linha descritiva de uma pendência para confirmar/desambiguar."""
    nome = (item.get("category") or item.get("description") or "(sem nome)").strip()
    desc = (item.get("description") or "").strip()
    detalhe = f" — {desc}" if (item.get("category") and desc) else ""
    side = _side_label(item.get("type", "income"))
    venc = "venceu" if item.get("overdue") else "vence"
    return f"*{nome}*{detalhe} — {_brl(item.get('amount'))} ({side}, {venc} {_fmt_date(item.get('due_date'))})"


def _disambig_message(search: str, items: list, verbo: str) -> str:
    linhas = [f"Encontrei {len(items)} pendências com \"{search}\":", ""]
    for item in items:
        linhas.append(f"• {_item_line(item)}")
    linhas += ["", f"Qual delas você quer {verbo}? Me diga o nome exato ou mais detalhes."]
    return "\n".join(linhas)


def _find_and_pick(phone: str, search: str) -> tuple[dict | None, str | None]:
    """Resolve uma pendência. Retorna (item, None) se única; (None, msg) se 0 ou >1."""
    items = emdia.find_pending(phone, search)
    if not items:
        return None, f"Não encontrei nenhuma pendência com \"{search}\". Verifique o nome ou a descrição."
    if len(items) > 1:
        return None, None  # caller decide a mensagem (precisa do verbo)
    return items[0], None


def _execute_op(phone: str, op: dict | None) -> str:
    """Executa a ação previamente confirmada (ou a alternativa do 'não')."""
    if not op:
        return "Ok, cancelei. 👍"
    kind = op.get("op")

    if kind == "mark_paid":
        r = emdia.edit_pending(phone, op["item_id"], mark_paid=True)
        if not r.get("success"):
            return "Não consegui dar baixa nessa pendência (talvez já tenha sido alterada)."
        verbo = "recebido" if op.get("type") == "income" else "pago"
        msg = f"✅ *{op.get('display', 'Item')}* marcado como {verbo}. Saldo na conta: {_brl(r.get('account_balance', 0))}."
        if op.get("type") == "expense":
            msg += _budget_notice(phone)  # dar baixa numa conta = saída paga; checa o teto
        return msg

    if kind == "edit":
        r = emdia.edit_pending(
            phone, op["item_id"],
            amount=op.get("amount"),
            due_date=op.get("due_date"),
            description=op.get("description"),
        )
        if not r.get("success"):
            return "Não consegui editar essa pendência (talvez já tenha sido alterada)."
        changes = []
        if op.get("amount") is not None:
            changes.append(f"valor → {_brl(op['amount'])}")
        if op.get("due_date"):
            changes.append(f"data → {_fmt_date(op['due_date'])}")
        if op.get("description"):
            changes.append(f"descrição → {op['description']}")
        return f"✅ *{op.get('display', 'Item')}* atualizado: {', '.join(changes)}."

    if kind == "delete":
        r = emdia.delete_pending(phone, op["item_id"])
        if not r.get("success"):
            return "Não consegui excluir essa pendência (talvez já tenha sido alterada)."
        return f"✅ Pendência *{op.get('display', 'Item')}* excluída."

    if kind == "register":
        a = op.get("args", {})
        r = emdia.register(
            phone=phone, type_=a.get("type", "expense"), amount=float(a.get("amount", 0)),
            description=a.get("description") or "", category=a.get("category"),
            payment_method=a.get("payment_method"), status=a.get("status", "paid"),
            due_date=a.get("due_date"), service_type=a.get("service_type"),
        )
        if not r.get("success"):
            return "Não encontrei seu cadastro. Confirme seu número no EmDia."
        verbo = "Entrada" if a.get("type") == "income" else "Saída"
        if a.get("status") == "pending":
            extra = f" (a {'receber' if a.get('type') == 'income' else 'pagar'})"
            return f"✅ {verbo} de {_brl(a.get('amount'))} registrada{extra}."
        return f"✅ {verbo} de {_brl(a.get('amount'))} registrada. Saldo na conta: {_brl(r.get('account_balance', 0))}."

    return "Ok."

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


def _budget_line(budget: float, spent: float) -> str:
    """Linha do controle de gastos: quanto já usou do teto do mês."""
    restante = budget - spent
    mes = _month_name(0)
    if restante < 0:
        return (f"⚠️ *Controle de gastos ({mes})*: você passou do limite!\n"
                f"Já usou {_brl(spent)} de {_brl(budget)} — *{_brl(abs(restante))} acima do teto*.")
    pct = int(round((spent / budget) * 100)) if budget > 0 else 0
    alerta = " ⚠️ perto do limite!" if pct >= 80 else ""
    return (f"📊 *Controle de gastos ({mes})*: já usou {_brl(spent)} de {_brl(budget)} "
            f"({pct}%). Resta *{_brl(restante)}*.{alerta}")


def _budget_notice(phone: str) -> str:
    """Após uma saída paga, retorna a linha do controle de gastos (ou '' se sem teto).
    Busca um resumo fresco para pegar o gasto do mês já atualizado."""
    try:
        s = emdia.get_summary(phone)
    except Exception:  # noqa: BLE001
        return ""
    budget = s.get("monthly_budget")
    if not budget or float(budget) <= 0:
        return ""
    spent = float((s.get("finance") or {}).get("paid_month", 0))
    return "\n\n" + _budget_line(float(budget), spent)


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
    budget = s.get("monthly_budget")
    if budget and float(budget) > 0:
        gasto = float(fin.get("paid_month", 0))
        L.append(f"Controle de gastos do mês (teto): {_brl(float(budget))} · já gasto (saídas pagas): "
                 f"{_brl(gasto)} · resta {_brl(float(budget) - gasto)}")

    def _itens(grupo: list) -> list:
        grupo = sorted(grupo, key=lambda x: x.get("due_date") or "9999")[:40]
        if not grupo:
            return ["  (nenhum)"]
        linhas = []
        for i in grupo:
            nome = (i.get("category") or "").strip()      # coluna "Nome" (cliente)
            desc = (i.get("description") or "").strip()    # o que foi vendido/pago
            svc = (i.get("service_type") or "").strip()    # tipo de serviço/produto
            label = nome or desc or "(sem descrição)"
            detalhe = f" ({desc})" if (nome and desc) else ""
            svc_info = f" [serviço: {svc}]" if svc else ""
            flag = " · VENCIDO" if i.get("overdue") else ""
            linhas.append(f"  - {label}{detalhe}{svc_info} · {_brl(i.get('amount'))} · vence {_fmt_date(i.get('due_date'))}{flag}")
        return linhas

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

    # CONFIRMAÇÃO PENDENTE: se há uma ação aguardando "sim/não", trata aqui antes
    # de qualquer interpretação (não chama o LLM para um simples sim/não).
    pending_conf = emdia.get_confirmation(phone)
    if pending_conf:
        if _is_yes(text):
            emdia.clear_confirmation(phone)
            reply = _execute_op(phone, pending_conf.get("on_yes"))
            _log(phone, text, reply)
            return reply
        if _is_no(text):
            emdia.clear_confirmation(phone)
            reply = _execute_op(phone, pending_conf.get("on_no"))
            _log(phone, text, reply)
            return reply
        # Não é sim nem não: abandona a confirmação (seguro: não executa nada
        # destrutivo) e processa a nova mensagem normalmente.
        emdia.clear_confirmation(phone)

    # Memória curta: histórico ANTES de processar a mensagem atual.
    history = emdia.recent_messages(phone)
    descriptions = emdia.get_descriptions(phone)
    action = llm.interpret(text, history, descriptions)
    a = action.get("action")

    if a in ("registrar", "definir_saldo", "definir_orcamento", "editar", "excluir"):
        # Escrita: caminho estruturado e seguro (valores exatos, sem alucinação).
        reply = _do_action(phone, text, action, s)
    else:
        # Leitura: MODO INTELIGENTE — o LLM compõe a resposta a partir dos dados
        # reais (responde perguntas compostas e variadas). Se falhar (sem API
        # key/erro), cai no modo estruturado como rede de segurança.
        reply = llm.answer(text, history, _snapshot_text(s)) or _answer_structured(s, action)

    if reply:
        reply = _fix_spacing(reply)
        _log(phone, text, reply)
    return reply


def _log(phone: str, user_text: str, reply: str) -> None:
    """Grava o par (pergunta, resposta) na memória da conversa."""
    if reply:
        emdia.log_message(phone, "user", user_text)
        emdia.log_message(phone, "assistant", reply)


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
        if consulta == "orcamento":
            budget = s.get("monthly_budget")
            if not budget or float(budget) <= 0:
                return ("Você ainda não tem um controle de gastos definido. "
                        "Ex.: \"define um controle de gastos de 3000\".")
            spent = float(fin.get("paid_month", 0))
            return _budget_line(float(budget), spent)
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


def _do_edit(phone: str, action: dict) -> str:
    """Resolve a pendência e PEDE CONFIRMAÇÃO antes de editar/marcar como pago."""
    search = (action.get("search") or "").strip()
    if not search:
        return "Qual pendência você quer editar? Ex.: \"muda o valor da Juliana para 1800\"."

    item, err = _find_and_pick(phone, search)
    if err:
        return err
    if item is None:  # múltiplos: pede para especificar
        return _disambig_message(search, emdia.find_pending(phone, search), "editar")

    mark_paid = action.get("mark_paid", False)
    new_amount = action.get("new_amount")
    new_due_date = action.get("new_due_date")
    new_description = action.get("new_description")

    if not mark_paid and new_amount is None and new_due_date is None and new_description is None:
        return "O que você quer mudar? Ex.: \"muda o valor da Juliana para 1800\" ou \"muda a data para dia 15\"."

    item_id = str(item["id"])
    nome_display = (item.get("category") or item.get("description") or "item").strip()
    tipo = item.get("type", "income")

    if mark_paid:
        verbo = "recebido" if tipo == "income" else "pago"
        efeito = "somar no" if tipo == "income" else "subtrair do"
        emdia.set_confirmation(phone, {
            "on_yes": {"op": "mark_paid", "item_id": item_id, "type": tipo, "display": nome_display},
        })
        return (f"Confirmar baixa: {_item_line(item)}\n\n"
                f"Vou marcar como {verbo} e {efeito} saldo. Responda *sim* para confirmar ou *não* para cancelar.")

    # Edição de campos (valor/data/descrição)
    changes = []
    if new_amount is not None:
        changes.append(f"valor: {_brl(item.get('amount'))} → *{_brl(new_amount)}*")
    if new_due_date:
        changes.append(f"data: {_fmt_date(item.get('due_date'))} → *{_fmt_date(new_due_date)}*")
    if new_description:
        changes.append(f"descrição → *{new_description}*")
    emdia.set_confirmation(phone, {
        "on_yes": {"op": "edit", "item_id": item_id, "display": nome_display,
                   "amount": new_amount, "due_date": new_due_date, "description": new_description},
    })
    return (f"Confirmar alteração em *{nome_display}*:\n" + "\n".join(f"• {c}" for c in changes) +
            "\n\nResponda *sim* para confirmar ou *não* para cancelar.")


def _do_delete(phone: str, action: dict) -> str:
    """Resolve a pendência e PEDE CONFIRMAÇÃO antes de excluir."""
    search = (action.get("search") or "").strip()
    if not search:
        return "Qual pendência você quer excluir?"

    item, err = _find_and_pick(phone, search)
    if err:
        return err
    if item is None:  # múltiplos
        return _disambig_message(search, emdia.find_pending(phone, search), "excluir")

    item_id = str(item["id"])
    nome_display = (item.get("category") or item.get("description") or "item").strip()
    emdia.set_confirmation(phone, {
        "on_yes": {"op": "delete", "item_id": item_id, "display": nome_display},
    })
    return (f"Confirmar exclusão: {_item_line(item)}\n\n"
            f"⚠️ Isso apaga a pendência e *não pode ser desfeito*. Responda *sim* para excluir ou *não* para cancelar.")


def _do_action(phone: str, text: str, action: dict, s: dict) -> str | None:
    """Escritas: registrar, definir saldo, editar e excluir pendências."""
    a = action.get("action")

    if a == "editar":
        return _do_edit(phone, action)

    if a == "excluir":
        return _do_delete(phone, action)

    if a == "definir_saldo":
        bal = action.get("balance")
        if bal is None:
            return "Quanto você tem na conta? Ex.: \"meu saldo é 3000\"."
        r = emdia.set_balance(phone, float(bal))
        if not r.get("success"):
            return "Não encontrei seu cadastro para atualizar o saldo."
        return f"✅ Saldo na conta atualizado para {_brl(r['account_balance'])}."

    if a == "definir_orcamento":
        if action.get("remove_budget"):
            r = emdia.set_budget(phone, None)
            if not r.get("success"):
                return "Não encontrei seu cadastro para remover o controle de gastos."
            return "✅ Controle de gastos removido. Você não terá mais avisos de limite."
        budget = action.get("budget")
        if budget is None or float(budget) <= 0:
            return ("Qual valor de controle de gastos você quer para o mês? "
                    "Ex.: \"define um controle de gastos de 3000\".")
        r = emdia.set_budget(phone, float(budget))
        if not r.get("success"):
            return "Não encontrei seu cadastro para definir o controle de gastos."
        spent = float((s.get("finance") or {}).get("paid_month", 0))
        return (f"✅ Controle de gastos definido: *{_brl(budget)}* por mês.\n"
                + _budget_line(float(budget), spent))

    # a == "registrar"
    amount = action.get("amount")
    if not amount:
        return "Não entendi o valor. Ex.: \"paguei 150 de luz\" ou \"recebi 2000 do cliente\"."
    type_ = action.get("type", "expense")
    status = action.get("status", "paid")
    name = action.get("name")

    reg_args = {
        "type": type_,
        "amount": float(amount),
        "description": action.get("description") or text[:80],
        "category": name,  # nome do cliente -> coluna "Nome" no app
        "payment_method": action.get("payment_method"),
        "status": status,
        "due_date": action.get("due_date"),
        "service_type": action.get("service_type"),
    }

    # PONTE DE QUITAÇÃO: ao registrar algo JÁ PAGO em nome de alguém, verifica se
    # já existe uma pendência aberta do mesmo lado com esse nome. Se existir, em vez
    # de duplicar, oferece dar baixa nela (evita conta em dobro).
    if status == "paid" and name:
        match = _match_open_pending(phone, name, type_, float(amount))
        if match:
            emdia.set_confirmation(phone, {
                "on_yes": {"op": "mark_paid", "item_id": str(match["id"]),
                           "type": type_, "display": (match.get("category") or name).strip()},
                "on_no": {"op": "register", "args": reg_args},
            })
            verbo_baixa = "recebida" if type_ == "income" else "paga"
            return (f"Você já tem esta pendência em aberto:\n{_item_line(match)}\n\n"
                    f"Quer dar baixa nela (marcar como {verbo_baixa})? Responda *sim*.\n"
                    f"Se for um lançamento novo e separado, responda *não*.")

    r = emdia.register(phone=phone, type_=reg_args["type"], amount=reg_args["amount"],
                       description=reg_args["description"], category=reg_args["category"],
                       payment_method=reg_args["payment_method"], status=reg_args["status"],
                       due_date=reg_args["due_date"], service_type=reg_args["service_type"])
    if not r.get("success"):
        return "Não encontrei seu cadastro. Confirme seu número no EmDia."
    verbo = "Entrada" if type_ == "income" else "Saída"
    if status == "pending":
        extra = f" (a {'receber' if type_ == 'income' else 'pagar'})"
        return f"✅ {verbo} de {_brl(amount)} registrada{extra}."
    msg = f"✅ {verbo} de {_brl(amount)} registrada. Saldo na conta: {_brl(r.get('account_balance', 0))}."
    if type_ == "expense":
        msg += _budget_notice(phone)  # aviso de controle de gastos, se houver teto
    return msg


def _match_open_pending(phone: str, name: str, type_: str, amount: float) -> dict | None:
    """Procura uma pendência aberta do mesmo lado (income/expense) com esse nome.
    Prioriza valor igual; senão, a de vencimento mais próximo. Retorna None se nenhuma."""
    candidatos = [i for i in emdia.find_pending(phone, name) if i.get("type") == type_]
    if not candidatos:
        return None
    iguais = [i for i in candidatos if abs(float(i.get("amount", 0)) - amount) < 0.01]
    if iguais:
        return iguais[0]
    # sem valor igual: só oferece baixa se houver UMA pendência (evita escolher errado)
    return candidatos[0] if len(candidatos) == 1 else None
