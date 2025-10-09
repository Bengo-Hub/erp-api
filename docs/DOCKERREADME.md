## Getting Started

### 1. Create MySQL User and Grant Privileges:

Run the following commands in your MySQL terminal to create a new user with backup privileges:

```sql
CREATE USER 'superuser'@'%' IDENTIFIED BY 'Super@2025';
GRANT ALL PRIVILEGES ON bengo_erp.* TO 'superuser'@'%';
FLUSH PRIVILEGES;
````
### 2. Configure a bind address to enable the docker MySQL instance to connect to the host machine's MySQL instance
   -  Create *my.ini* file at the root of the MySQL installation directory if it does not exist already
   - Add this line or uncomment if already exist

     ```sh
        bind-address=0.0.0.0
    ```

To use this Docker image, follow these steps:

Pull the Docker image from Docker Hub using the following commands:
````sh
docker pull titusdev/bengo_erp_api
````
Run the Docker container with the necessary settings:
````sh
docker run -d \
  --name bengo_erp_api \
  -p 8000:8000 \
  -e DEBUG=False \
  -e DB_HOST=192.168.8.113 \
  -e DB_PORT=3306 \
  -e DB_NAME=bengo_erp \
  -e DB_USER=root \
  -e DB_PASSWORD=root \
  -e PYTHONUNBUFFERED=1 \
  -e DJANGO_SETTINGS_MODULE=ProcureProKEAPI.settings \
  bengo_erp_api_image
  ````

### 3. Replace Environmental Variables

Before running the Docker container, replace the following environmental variables in the docker run command with your own values:

- `MYSQL_USER`: The MySQL user with backup privileges.
- `MYSQL_PASSWORD`: Password for the MySQL user.
- `MYSQL_HOST`: IP address of the MySQL host machine.
- `MYSQL_PORT`: MySQL port (default: 3306).
- `DATABASE_NAME`: The name of the database to be backed up.
- `HOST_DIR`: Directory path on the host machine to map the container's backup directory and store backup files.
- `DESIRED_BACKUP_TIME`: Desired daily backup time in 24 HR clock system (e.g., 0200 for 2 AM).
- `TZ`: Timezone for the Docker container to use. Default is Africa/Nairobi.

### 4. MySQL User Permissions
Ensure that you have created a MySQL user with backup privileges (GRANT ALL) specifically for this script. This user should have the necessary privileges to perform backups on the specified database. It's recommended to avoid using the root user for security reasons.

4. The script will execute backups based on the set schedule.
***License
## License