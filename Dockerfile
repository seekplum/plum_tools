FROM python:3.12-slim

# Setup env
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONFAULTHANDLER 1

# Install invoke and compilation dependencies
# RUN sed -i 's#http://\(security\|deb\).debian.org#https://mirrors.tuna.tsinghua.edu.cn#g' /etc/apt/sources.list.d/debian.sources
# RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir invoke

WORKDIR /code

# Install python dependencies
COPY requirements.txt .
COPY requirements-dev.txt .
COPY tasks.py .
RUN inv install --dev

# Install application into container
COPY . .

# Run the executable
CMD ["/bin/bash", "-c", "env && inv --complete"]
