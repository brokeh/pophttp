FROM python:3.11-alpine

ADD config.py lifx.py pophttp.py requirements.txt README.md /pophttp/
RUN pip install --disable-pip-version-check -r /pophttp/requirements.txt

EXPOSE 56700/udp

WORKDIR /pophttp
ENTRYPOINT ["python3", "-u", "/pophttp/pophttp.py"]
