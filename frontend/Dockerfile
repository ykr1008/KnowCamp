# /frontend/Dockerfile
FROM node:22-alpine

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json* ./
RUN npm install

# Expose Vite's default port
EXPOSE 5173

# Start the React development server
CMD ["npm", "run", "dev", "--", "--host"]