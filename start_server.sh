#!/bin/bash
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
