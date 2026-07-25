#!/bin/bash
cd /home/finance/Tastytrade-API-GEX-Dashboard/
source venv/bin/activate
python3 mes_0dte_gamma_pipeline.py >> mes_pipeline_log.txt 2>&1
