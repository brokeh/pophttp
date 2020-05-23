FROM python:3-alpine

ADD lifx.py pophttp.py README.md /pophttp/

EXPOSE 56700/udp

WORKDIR /pophttp
ENTRYPOINT ["python3", "-u", "/pophttp/pophttp.py"]
