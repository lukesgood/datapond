FROM jupyter/scipy-notebook:latest

USER root

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

USER ${NB_UID}

# Python packages for DataPond
RUN pip install --no-cache-dir \
    duckdb==0.10.0 \
    pyiceberg==0.5.0 \
    boto3==1.34.0 \
    pandas==2.2.0 \
    matplotlib==3.8.0 \
    seaborn==0.13.0 \
    plotly==5.18.0 \
    scikit-learn==1.4.0 \
    xgboost==2.0.3 \
    lightgbm==4.3.0

# Iceberg + DuckDB helper script
COPY iceberg_helper.py /usr/local/lib/python3.11/site-packages/

# Example notebooks
COPY notebooks/ /home/${NB_USER}/work/examples/

USER ${NB_UID}
WORKDIR /home/${NB_USER}

# Auto-load helper on kernel start
RUN mkdir -p /home/${NB_USER}/.ipython/profile_default/startup && \
    echo "from iceberg_helper import connect_duckdb_iceberg, q" > /home/${NB_USER}/.ipython/profile_default/startup/00-datapond.py

EXPOSE 8888

CMD ["start-notebook.sh"]
