-- Drop index "employee_tenant_id_device_pin" from table: "employees"
DROP INDEX "employee_tenant_id_device_pin";
-- Drop index "employee_tenant_id_national_id" from table: "employees"
DROP INDEX "employee_tenant_id_national_id";
-- Create index "employee_tenant_id_device_pin" to table: "employees"
CREATE UNIQUE INDEX "employee_tenant_id_device_pin" ON "employees" ("tenant_id", "device_pin") WHERE ((device_pin IS NOT NULL) AND ((device_pin)::text <> ''::text));
-- Create index "employee_tenant_id_national_id" to table: "employees"
CREATE UNIQUE INDEX "employee_tenant_id_national_id" ON "employees" ("tenant_id", "national_id") WHERE ((national_id IS NOT NULL) AND ((national_id)::text <> ''::text));
