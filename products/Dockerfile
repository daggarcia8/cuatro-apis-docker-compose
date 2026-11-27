FROM node:24-slim
WORKDIR /app
COPY package.json .
RUN npm install --omit=dev && mkdir -p /data
COPY server.js .
ENV DB_PATH=/data/products.db
EXPOSE 8003
CMD ["npm", "start"]
