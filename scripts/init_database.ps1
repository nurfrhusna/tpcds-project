
$ErrorActionPreference = "Stop"

$container = "tpcds-clickhouse"
$database = "tpcds_test"

$projectDir = Split-Path -Parent $PSScriptRoot
$schemaPath = Join-Path $projectDir "schema\create_tables_nullable.sql"

if (-not (Test-Path $schemaPath)) {
    throw "Schema file not found: $schemaPath"
}

Write-Host "Creating database $database..."

docker exec $container clickhouse-client `
    --query "CREATE DATABASE IF NOT EXISTS $database"

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create database"
}

Write-Host "Creating TPC-DS tables..."

Get-Content $schemaPath -Raw |
    docker exec -i $container clickhouse-client `
        --database=$database `
        --multiquery

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create tables"
}

Write-Host "Database initialization completed."
