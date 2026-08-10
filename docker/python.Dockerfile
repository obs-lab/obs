FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libpng16-16 \
        libgomp1 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        numpy==1.26.4 \
        pandas==2.2.3 \
        matplotlib==3.9.2 \
        seaborn==0.13.2 \
        scipy==1.13.1 \
        statsmodels==0.14.4 \
        scikit-learn==1.5.2

ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/mpl

RUN mkdir -p /tmp/mpl && chmod 777 /tmp/mpl

RUN python -c "\
import matplotlib.pyplot as plt; \
import statsmodels.api as sm; \
from sklearn.covariance import MinCovDet; \
from sklearn.linear_model import HuberRegressor, TheilSenRegressor; \
plt.figure(); \
print('Python pronto: matplotlib, statsmodels, scikit-learn')"
