# EmailPet Backend

Backend service for EmailPet — an AI Native desktop email pet powered by a LangGraph agent.

## Install

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in your IMAP/SMTP credentials and LLM API key.

```bash
cp config.example.yaml config.yaml
```

## Run Tests

```bash
pytest
```

## Start the Server

```bash
python -m emailpet.main
```
