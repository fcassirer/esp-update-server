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
RUN mkdir -p /usr/local/bin
RUN FRONTAIL_VERSION=`curl https://github.com/mthenw/frontail/releases/latest 2>/dev/null | grep -Po 'v[0-9]+.[0-9]+.[0-9]+'` && \
  wget -O /usr/local/bin/frontail https://github.com/mthenw/frontail/releases/download/${FRONTAIL_VERSION}/frontail-linux;chmod +x /usr/local/bin/frontail
WORKDIR /esp-update-server
RUN python3 -m pip install --upgrade pip
RUN pip3 install -r requirements.txt
EXPOSE 5000 9001
CMD ESP_CONFIG=esp-container-config.cfg  python3 ./server.py
