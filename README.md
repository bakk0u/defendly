# Defendly — AI Interview Preparation Agent

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

Install the backend packages:

```bat
cd /d "C:\Users\anasb\Documents\interview agent"
"C:\Users\anasb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pip install -r backend\requirements.txt
```

Start the API in the first Command Prompt:

```bat
cd /d "C:\Users\anasb\Documents\interview agent"
set JWT_SECRET=change-this-local-secret
set OLLAMA_ENABLED=true
set OLLAMA_MODEL=qwen2.5:7b-instruct
set OLLAMA_BASE_URL=http://127.0.0.1:11434
"C:\Users\anasb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Start the web app in a second Command Prompt:

```bat
cd /d "C:\Users\anasb\Documents\interview agent"
npm install
npm run dev
```

Open `http://localhost:3001`. API documentation is available at `http://localhost:8000/docs`.

### Docker mode

Docker starts the frontend, backend, Ollama, downloads the configured model once, and keeps both the model and database in named volumes:

```bat
cd /d "C:\Users\anasb\Documents\interview agent"
set JWT_SECRET=replace-with-a-long-random-secret
set OLLAMA_MODEL=qwen2.5:7b-instruct
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

1. Push the repository to GitHub.
2. In Render, choose **New > Blueprint** and select the repository.
3. Render reads `render.yaml` and creates the API, web service, secret, and persistent disk.
4. Add at least one provider key when prompted if you want cloud AI. Without a key, the deterministic fallback still works.
5. After deployment, set `DEFAULT_LLM_PROVIDER` on the API to `openai`, `anthropic`, or `gemini` if desired.

A hosted API cannot reach Ollama on your laptop. For cloud inference, use one of the configured cloud providers or host Ollama on reachable GPU infrastructure.

## Verification

```bat
npm test
"C:\Users\anasb\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -c "from backend.test_api import test_authenticated_cv_to_realtime_ready_flow; test_authenticated_cv_to_realtime_ready_flow(); print('backend tests passed')"
```

The backend test covers registration, authenticated CV extraction, question generation, evaluation, mastery scoring, provider discovery, and the WebSocket interview flow.
