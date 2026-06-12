#!/usr/bin/env python3
"""
Validation script for Insect Lake project structure
Checks all required files exist and have proper structure
"""

import os
import json
import sys
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Required files and directories
REQUIRED_STRUCTURE = {
    'directories': [
        'api',
        'airflow/dags',
        'scripts',
    ],
    'files': {
        'root': [
            'README.md',
            'QUICKSTART.md',
            'BENCHMARKS.md',
            'DEPLOYMENT.md',
            'docker-compose.yml',
            '.env.example',
            '.gitignore',
            'Makefile',
            'LICENSE',
        ],
        'api': [
            'main.py',
            'config.py',
            'db.py',
            'schemas.py',
            'requirements.txt',
            'Dockerfile',
        ],
        'scripts': [
            'init_db.sql',
            'load_gbif.py',
            'fast_ingestor.py',
            'transform_to_curated.py',
            'test_integration.py',
        ],
        'airflow/dags': [
            'ingest_inaturalist_dag.py',
        ],
    }
}

class ProjectValidator:
    """Validate project structure and files"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.checks_passed = 0
        self.checks_total = 0
    
    def check_directory(self, path):
        """Check if directory exists"""
        self.checks_total += 1
        full_path = PROJECT_ROOT / path
        if full_path.exists() and full_path.is_dir():
            self.checks_passed += 1
            return True
        else:
            self.errors.append(f"Missing directory: {path}")
            return False
    
    def check_file(self, path):
        """Check if file exists and is not empty"""
        self.checks_total += 1
        full_path = PROJECT_ROOT / path
        if not full_path.exists():
            self.errors.append(f"Missing file: {path}")
            return False
        
        if full_path.stat().st_size == 0:
            self.warnings.append(f"Empty file: {path}")
            return False
        
        self.checks_passed += 1
        return True
    
    def check_python_file(self, path):
        """Check Python file syntax"""
        self.checks_total += 1
        full_path = PROJECT_ROOT / path
        
        if not self.check_file(path):
            return False
        
        try:
            with open(full_path, 'r') as f:
                compile(f.read(), str(full_path), 'exec')
            self.checks_passed += 1
            return True
        except SyntaxError as e:
            self.errors.append(f"Syntax error in {path}: {e}")
            return False
    
    def check_json_file(self, path):
        """Check JSON file validity"""
        self.checks_total += 1
        full_path = PROJECT_ROOT / path
        
        if not full_path.exists():
            self.errors.append(f"Missing file: {path}")
            return False
        
        try:
            with open(full_path, 'r') as f:
                json.load(f)
            self.checks_passed += 1
            return True
        except json.JSONDecodeError as e:
            self.errors.append(f"Invalid JSON in {path}: {e}")
            return False
    
    def check_docker_compose(self):
        """Check docker-compose.yml structure"""
        self.checks_total += 1
        path = PROJECT_ROOT / 'docker-compose.yml'
        
        if not path.exists():
            self.errors.append("Missing docker-compose.yml")
            return False
        
        try:
            import yaml
            with open(path) as f:
                config = yaml.safe_load(f)
            
            required_services = ['minio', 'postgres', 'airflow', 'api']
            existing_services = list(config.get('services', {}).keys())
            
            for service in required_services:
                if service not in existing_services:
                    self.errors.append(f"Missing service '{service}' in docker-compose.yml")
                    return False
            
            self.checks_passed += 1
            return True
        except Exception as e:
            self.errors.append(f"Error parsing docker-compose.yml: {e}")
            return False
    
    def check_requirements_txt(self):
        """Check requirements.txt for key packages"""
        self.checks_total += 1
        path = PROJECT_ROOT / 'api' / 'requirements.txt'
        
        if not path.exists():
            self.errors.append("Missing api/requirements.txt")
            return False
        
        required_packages = [
            'fastapi',
            'uvicorn',
            'psycopg2-binary',
            'minio',
            'h3',
            'numpy',
            'pandas',
        ]
        
        with open(path) as f:
            content = f.read().lower()
        
        missing = []
        for pkg in required_packages:
            if pkg not in content:
                missing.append(pkg)
        
        if missing:
            self.errors.append(f"Missing packages in requirements.txt: {', '.join(missing)}")
            return False
        
        if 'anthropic' in content:
            self.warnings.append("⚠ Found 'anthropic' in requirements.txt - should be removed")
            return False
        
        self.checks_passed += 1
        return True
    
    def run_all_checks(self):
        """Run all validation checks"""
        print("🔍 Validating Insect Lake Project Structure\n")
        print("="*60)
        
        # Check directories
        print("\n📁 Checking directories...")
        for directory in REQUIRED_STRUCTURE['directories']:
            status = "✓" if self.check_directory(directory) else "✗"
            print(f"  {status} {directory}/")
        
        # Check files
        print("\n📄 Checking files...")
        for location, files in REQUIRED_STRUCTURE['files'].items():
            print(f"\n  {location}/")
            for filename in files:
                if location == 'root':
                    path = filename
                else:
                    path = f"{location}/{filename}"
                
                # Use appropriate checker
                if filename.endswith('.py'):
                    status = "✓" if self.check_python_file(path) else "✗"
                elif filename.endswith('.json'):
                    status = "✓" if self.check_json_file(path) else "✗"
                else:
                    status = "✓" if self.check_file(path) else "✗"
                
                print(f"    {status} {filename}")
        
        # Special checks
        print("\n🔧 Special validation checks...")
        
        print(f"  {'✓' if self.check_docker_compose() else '✗'} docker-compose.yml structure")
        print(f"  {'✓' if self.check_requirements_txt() else '✗'} requirements.txt packages")
        
        # Check .env.example
        self.checks_total += 1
        if (PROJECT_ROOT / '.env.example').exists():
            env_content = (PROJECT_ROOT / '.env.example').read_text()
            if 'ANTHROPIC_API_KEY' in env_content:
                self.warnings.append("⚠ .env.example still contains ANTHROPIC_API_KEY reference")
            else:
                self.checks_passed += 1
                print("  ✓ .env.example (cleaned)")
        else:
            self.errors.append("Missing .env.example")
        
        # Print summary
        print("\n" + "="*60)
        print(f"\n📊 Validation Summary")
        print(f"  Total checks: {self.checks_total}")
        print(f"  Passed: {self.checks_passed}")
        print(f"  Failed: {len(self.errors)}")
        print(f"  Warnings: {len(self.warnings)}")
        
        if self.errors:
            print(f"\n❌ Errors ({len(self.errors)}):")
            for error in self.errors:
                print(f"  • {error}")
        
        if self.warnings:
            print(f"\n⚠️  Warnings ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        success = len(self.errors) == 0
        status = "✅ VALID" if success else "❌ INVALID"
        print(f"\n{status}\n")
        
        return success

def main():
    validator = ProjectValidator()
    success = validator.run_all_checks()
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
