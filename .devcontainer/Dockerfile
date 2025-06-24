# See here for image contents: https://github.com/microsoft/vscode-dev-containers/tree/v0.209.6/containers/python-3/.devcontainer/base.Dockerfile

# [Choice] Python version (use -bullseye variants on local arm64/Apple Silicon): 3, 3.10, 3.9, 3.8, 3.7, 3.6, 3-bullseye, 3.10-bullseye, 3.9-bullseye, 3.8-bullseye, 3.7-bullseye, 3.6-bullseye, 3-buster, 3.10-buster, 3.9-buster, 3.8-buster, 3.7-buster, 3.6-buster
ARG VARIANT="3.12"
FROM alpine:latest AS dependencies

USER root

RUN apk update && \
    apk add python3 python3-dev py3-pip

RUN mkdir /root/ibm && cd /root/ibm && \
    wget https://public.dhe.ibm.com/ibmdl/export/pub/software/websphere/messaging/mqdev/redist/9.4.0.6-IBM-MQC-Redist-LinuxX64.tar.gz -O - | tar xzf -
#    wget https://ibm.biz/IBM-MQC-Redist-LinuxX64targz  -O - | tar xzf -

FROM mcr.microsoft.com/vscode/devcontainers/python:1-${VARIANT}

RUN mkdir -p /opt/mqm

COPY --from=dependencies /root/ibm /opt/mqm

ENV LD_LIBRARY_PATH="/opt/mqm/lib64:${LD_LIBRARY_PATH}"
ENV PATH="/opt/mqm/bin:${PATH}"
ENV LANG="C.UTF-8"

# run github workflows locally
RUN curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# [Optional] Uncomment this section to install additional OS packages.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends vim

RUN python -m pip install --upgrade pip

RUN rm -rf /etc/localtime || true

ARG USERNAME=vscode

RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
    && mkdir /commandhistory \
    && touch /commandhistory/.bash_history \
    && chown -R $USERNAME /commandhistory \
    && echo "$SNIPPET" >> "/home/$USERNAME/.bashrc"
