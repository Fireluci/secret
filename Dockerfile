FROM python:3.10.8-slim-buster

RUN apt update && apt install -y git
COPY requirements.txt /requirements.txt

RUN pip3 install -U pip && pip3 install -U -r requirements.txt
RUN mkdir /ben-url-filter-bot
WORKDIR /ben-url-filter-bot
COPY start.sh /start.sh
CMD ["/bin/bash", "/start.sh"]
