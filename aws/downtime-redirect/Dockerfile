FROM kyma/docker-nginx

# Set up files to serve
COPY sg_server_maintenance_tr_promo.html /var/www/index.html

# Set up SSL.
# /etc/nginx/ssl must be connected to a volume that has the files:
# server.crt
# server.key
RUN ln -s /etc/nginx/sites-available/default-ssl /etc/nginx/sites-enabled/default-ssl

CMD 'nginx'

# then:
# docker build -t sg-server-maintenance-tr-promo .
# docker tag sg-server-maintenance-tr-promo localhost:5000/sg-server-maintenance-tr-promo
# docker push localhost:5000/sg-server-maintenance-tr-promo
