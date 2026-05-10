FROM php:8.2-apache 
#Download da imagem oficial que já vem com o PHP 8.2 e o servidor web Apache pré-instalados e configurados

WORKDIR /var/www/html
#Define a pasta root 

RUN apt-get update && apt-get install -y libmariadb-dev
#Atualiza a lista de pacotes disponíveis instala as bibliotecas de desenvolvimento do MariaDB, necessárias para que o PHP consiga compilar extensões de base de dados.

RUN docker-php-ext-install mysqli
#Compila e instala a extensão mysqli (por exemplo,  para utilizar  mysqli_connect()) 


# Instalar dependências para a extensão MongoDB
RUN apt-get update && apt-get install -y \
    libssl-dev \
    pkg-config \
    autoconf # Adicione autoconf
RUN pecl install mongodb 
RUN docker-php-ext-enable mongodb	

RUN apt-get clean && rm -rf /var/lib/apt/lists/*
#Apagas ficheiros temporários e as listas de pacotes que foram descarregadas nos passos anteriores. 
