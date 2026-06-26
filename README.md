# EmDia · Agente de IA (WhatsApp)

Serviço Python (FastAPI) que conecta o WhatsApp (via Evolution API) ao EmDia.
Fluxo: **WhatsApp → Evolution API (webhook) → este serviço → LLM interpreta → Supabase (RPC) → resposta no WhatsApp**.

## O que o agente entende
- "paguei 150 de luz no pix" → registra **despesa paga** e desconta do **Saldo na Conta**
- "recebi 2000 do cliente" → registra **receita paga** e soma no Saldo na Conta
- "vou pagar 300 de internet dia 10" → registra **conta a pagar (pendente)**
- "meu saldo é 3000" → ajusta o Saldo na Conta
- "qual meu saldo?" / "resumo" → manda o **relatório** (saldo, a receber, a pagar, vencidos, metas)

## 1. Instalar
```bash
cd agent
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
# source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configurar
```bash
cp .env.example .env   # (Windows: copy .env.example .env)
```
Edite o `.env`:
- `SUPABASE_SERVICE_KEY` = a secret key do Supabase (sb_secret_...).
- Deixe `LLM_PROVIDER=rule` para testar **sem nenhuma API key** (interpretação básica por regras).
- Depois, para usar IA de verdade: `LLM_PROVIDER=openai|gemini|anthropic` + `LLM_API_KEY=...`
  (e `pip install openai` / `google-generativeai` / `anthropic`).

## 3. Rodar
```bash
uvicorn main:app --reload --port 8000
```

## 4. Testar SEM WhatsApp
O número precisa estar cadastrado em `profiles.phone` no Supabase.
```bash
curl -X POST http://localhost:8000/test \
  -H "Content-Type: application/json" \
  -d '{"phone":"5511999998888","text":"paguei 150 de luz no pix"}'
```

## 5. Conectar ao WhatsApp (quando tiver a Evolution API)
1. Preencha `EVOLUTION_BASE_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE` no `.env`.
2. Exponha o serviço (local): `ngrok http 8000` → copie a URL https.
3. Configure o **webhook da instância** na Evolution apontando para `https://SEU_NGROK/webhook`
   (eventos de mensagem recebida — `messages.upsert`).
4. Escaneie o **QR Code** na Evolution e mande mensagem para o número.

## Pré-requisito importante
Cada cliente precisa ter o **número de WhatsApp salvo** em `profiles.phone` no EmDia
(é como o agente sabe de quem é a mensagem). Falta criar esse campo no app — peça para adicionarmos.
