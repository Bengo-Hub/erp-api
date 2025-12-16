#!/usr/bin/env pwsh
# clean_migrations.ps1
# Removes all Django migration files except __init__.py in all apps under erp-api

param(
    [string]$RootPath = (Split-Path -Parent $PSScriptRoot),
    [switch]$DryRun = $false
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Django Migrations Cleanup Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN MODE] No files will be deleted" -ForegroundColor Yellow
    Write-Host ""
}

$deletedCount = 0
$skippedCount = 0

# Find all migration directories, excluding venv, node_modules, and .git
$migrationDirs = Get-ChildItem -Path $RootPath -Directory -Recurse -Filter "migrations" -ErrorAction SilentlyContinue | 
    Where-Object { $_.FullName -notmatch "\\(venv|node_modules|\\.git|__pycache__)" }

Write-Host "Found $($migrationDirs.Count) migration directories" -ForegroundColor Green
Write-Host ""

foreach ($dir in $migrationDirs) {
    Write-Host "Processing: $($dir.FullName)" -ForegroundColor Cyan
    
    # Get all .py files in the migrations directory
    $migrationFiles = Get-ChildItem -Path $dir.FullName -File -Filter "*.py" | 
        Where-Object { $_.Name -ne "__init__.py" }
    
    if ($migrationFiles.Count -eq 0) {
        Write-Host "  [OK] No migration files to delete (only __init__.py exists)" -ForegroundColor Gray
        $skippedCount++
    } else {
        foreach ($file in $migrationFiles) {
            if ($DryRun) {
                Write-Host "  [DRY RUN] Would delete: $($file.Name)" -ForegroundColor Yellow
            } else {
                try {
                    Remove-Item -Path $file.FullName -Force
                    Write-Host "  [DELETED] $($file.Name)" -ForegroundColor Green
                    $deletedCount++
                } catch {
                    Write-Host "  [ERROR] Failed to delete: $($file.Name) - $($_.Exception.Message)" -ForegroundColor Red
                }
            }
        }
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "Would delete: $deletedCount migration file(s)" -ForegroundColor Yellow
    Write-Host "Skipped: $skippedCount directory/ies (no files to delete)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Run without -DryRun to actually delete the files" -ForegroundColor Yellow
} else {
    Write-Host "Deleted: $deletedCount migration file(s)" -ForegroundColor Green
    Write-Host "Skipped: $skippedCount directory/ies (no files to delete)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "[SUCCESS] Cleanup complete!" -ForegroundColor Green
}
