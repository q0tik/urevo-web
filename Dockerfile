FROM nginx:alpine

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html discover.html /usr/share/nginx/html/

EXPOSE 80
