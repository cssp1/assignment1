FROM kyma/docker-nginx

# Override kyma's config with ours
COPY default /etc/nginx/sites-enabled/default
COPY default-ssl /etc/nginx/sites-available/default-ssl

# Set up SSL.
# /etc/nginx/ssl must be connected to a volume that has the files:
# server.crt
# server.key
RUN ln -s /etc/nginx/sites-available/default-ssl /etc/nginx/sites-enabled/default-ssl

# Set up files to serve
COPY sg_server_maintenance_tr_promo.html /var/www/index.html

CMD 'nginx'

# then:
# docker build -t sg-server-maintenance-tr-promo .
# docker tag sg-server-maintenance-tr-promo localhost:5000/sg-server-maintenance-tr-promo
# ../bootstrap/run-docker-registry.sh (ensure your ~/.ssh/HOSTNAME-awssecret is set up)
# docker push localhost:5000/sg-server-maintenance-tr-promo
