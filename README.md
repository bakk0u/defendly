# Defendly — AI Interview Preparation Agent

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/bakk0u/defendly)

Defendly turns every CV line into a personalized interview syllabus. It extracts evidence, generates targeted questions, evaluates answers, identifies concept gaps, and adapts future practice to the candidate's weakest areas.

## What is included

- Account registration and sign-in with Argon2 password hashing and signed session tokens
- CV text and PDF extraction with Pydantic-validated structured output
- LangChain prompt orchestration for extraction, question generation, and scoring
- Ollama, OpenAI, Anthropic, Google Gemini, and deterministic fallback providers
- TF-IDF concept coverage, confidence scoring, Bayesian mastery estimates, and adaptive question selection
- Live WebSocket interview sessions with saved messages and evaluations
- A normalized SQLite database for users, CVs, projects, skills, experiences, questions, attempts, chat sessions, messages, and mastery snapshots
- Responsive React + TypeScript interface
- Docker Compose for the web app, API, Ollama, model download, and persistent data
- A Render deployment blueprint

## Run locally on Windows

### Normal development mode

Download the recommended local model once:

```bat
ollama pull qwen3:14b
```

Clone the repository and install the backend packages:

```bat
git clone https://github.com/bakk0u/defendly.git
cd defendly
py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r backend\requirements.txt
```

Start the API in the first Command Prompt:

```bat
cd /d "path\to\defendly"
set JWT_SECRET=change-this-local-secret
set OLLAMA_ENABLED=true
set OLLAMA_MODEL=qwen3:14b
set OLLAMA_BASE_URL=http://127.0.0.1:11434
set DEFAULT_LLM_PROVIDER=ollama
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Start the web app in a second Command Prompt:

```bat
cd /d "path\to\defendly"
npm install
npm run dev
```

Open `http://localhost:3001`. API documentation is available at `http://localhost:8000/docs`.

### Docker mode

Docker starts the frontend, backend, Ollama, downloads the configured model once, and keeps both the model and database in named volumes:

```bat
cd /d "path\to\defendly"
set JWT_SECRET=replace-with-a-long-random-secret
set OLLAMA_MODEL=qwen3:14b
docker compose up --build
```

Then open `http://localhost:3001`.

## AI provider configuration

Ollama works locally without an API key. Cloud providers become selectable only after the corresponding environment variable is set:

```bat
set OPENAI_API_KEY=your-key
set ANTHROPIC_API_KEY=your-key
set GEMINI_API_KEY=your-key
```

Models can be overridden with `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GEMINI_MODEL`, or `OLLAMA_MODEL`. The fallback provider remains available for fast offline testing and never calls an external model.

## Deploy on Render

Click **Deploy to Render** above, or open Render and choose **New > Blueprint**, connect GitHub, and select this repository. Render reads `render.yaml` and creates:

- `defendly-web`, the public React application
- `defendly-api`, the FastAPI service
- a persistent disk for accounts, CVs, questions, and interview progress
- generated production session secrets and cross-service URLs

Enter `OPENAI_API_KEY` when Render prompts for secrets. The hosted deployment defaults to OpenAI; if the key is omitted or invalid, Defendly uses its deterministic fallback. The API uses a paid Render instance because persistent disks are not available on free web services.

After the first deployment succeeds, copy the `defendly-web` `onrender.com` URL. This is the link visitors use; they do not need Python, Node.js, Ollama, Docker, or any source packages installed.

To show the live application on the GitHub repository page, open the repository, click the gear next to **About**, paste the Render URL into **Website**, and save. From a terminal, the equivalent command is:

```bat
gh repo edit bakk0u/defendly --homepage "https://YOUR-DEFENDLY-WEB-URL.onrender.com"
```

A hosted API cannot reach Ollama on your laptop. For cloud inference, use one of the configured cloud providers or host Ollama on reachable GPU infrastructure.

## Verification

```bat
npm test
.venv\Scripts\python.exe -c "from backend.test_api import test_authenticated_cv_to_realtime_ready_flow; test_authenticated_cv_to_realtime_ready_flow(); print('backend tests passed')"
```

The backend test covers registration, authenticated CV extraction, question generation, evaluation, mastery scoring, provider discovery, and the WebSocket interview flow.
