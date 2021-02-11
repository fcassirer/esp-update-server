FROM ubuntu:focal

ARG TZ
ENV TZ=$TZ

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3.9 python3-pip \
    fonts-liberation libappindicator3-1 libasound2 libatk-bridge2.0-0 \
    libnspr4 libnss3 lsb-release xdg-utils libxss1 libdbus-glib-1-2 \
    libgbm1 \
    curl unzip wget \
    xvfb


COPY . /esp-update-server
WORKDIR /esp-update-server
RUN python3 -m pip install --upgrade pip
RUN pip3 install -r requirements.txt
EXPOSE 5000
CMD ESP_CONFIG=esp-container-config.cfg  python3 ./server.py
