"""
Web UI for Architecture Diagram Analyzer with IAC Generation
"""

import os
import json
import zipfile
import uuid
import threading
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, session, Response
from werkzeug.utils import secure_filename
import queue
import time

from .workflows.orchestrator import WorkflowOrchestrator, progress_queues
from .core.config import Config
from .utils.logging_config import setup_logging
from .utils.telemetry import initialize_telemetry, trace_operation, add_event, set_attribute

# Initialize logging
setup_logging(level="INFO")

# Initialize telemetry
config = Config.from_environment()
initialize_telemetry(
    service_name="architecture-diagram-agents",
    connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
    enabled=config.enable_telemetry
)

# DevUI has been removed - using built-in tracing instead
DEVUI_AVAILABLE = False

# Background job storage
iac_jobs = {}  # {job_id: {'status': 'pending|running|completed|failed', 'result': {}, 'error': None}}
analysis_jobs = {}  # Store analysis results with job IDs

# Load environment variables
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = str(Path(__file__).parent.parent / 'uploads')
app.config['TERRAFORM_FOLDER'] = str(Path(__file__).parent.parent / 'terraform_projects')
# Use fixed SECRET_KEY - generate one with: python -c "import secrets; print(secrets.token_hex(32))"
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production-12345678')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour

# Create folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TERRAFORM_FOLDER'], exist_ok=True)

@app.before_request
def make_session_permanent():
    """Make Flask sessions permanent so they persist across browser sessions."""
    session.permanent = True

# Global in-memory storage for analysis results (more reliable than session for complex objects)
analysis_results_store = {}

# Store last generated project path in memory (for demo purposes)
last_terraform_project = None

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/devui')
def devui_redirect():
    """Redirect to Agent Framework DevUI server."""
    if not DEVUI_AVAILABLE:
        return jsonify({
            'error': 'DevUI not available',
            'message': 'Please install agent-framework-devui: pip install agent-framework-devui --pre'
        }), 503
    
    # DevUI runs on separate port (8080 by default)
    return jsonify({
        'devui_url': 'http://localhost:8080',
        'message': 'Agent Framework DevUI is running on port 8080'
    })

@app.route('/analyze-only', methods=['POST'])
def analyze_only():
    """Analyze diagram only (CV + Analyzer Agent) - returns immediately."""
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, BMP'}), 400
    
    try:
        # Save file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Initialize orchestrator
        config = Config.from_environment()
        orchestrator = WorkflowOrchestrator(config=config)
        
        # Execute analyzer only
        result = orchestrator.execute_analyzer_only(filepath)
        
        # Convert Pydantic model to dict for session storage
        if hasattr(result, 'model_dump'):
            result_dict = result.model_dump()
        elif hasattr(result, 'dict'):
            result_dict = result.dict()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {}
        
        # NOTE: Session storage moved to after response is built (see below)
        # to ensure consistent structure between session and API response
        
        # Clean up uploaded file
        os.remove(filepath)
        
        # Build response in consistent format
        if isinstance(result, dict):
            response_data = {
                'success': True,
                'computer_vision': result.get('vision_result', {}),
                'agent_analysis': result.get('analyzer_result', {}),
                'best_practices': result.get('best_practices_result', {}),
                'workflow_status': result.get('workflow_status', 'success'),
                'errors': result.get('errors', [])
            }
        else:
            # Handle Pydantic model
            response_data = {
                'success': True,
                'computer_vision': result.vision_result if hasattr(result, 'vision_result') else {},
                'agent_analysis': result.analyzer_result if hasattr(result, 'analyzer_result') else {},
                'best_practices': result.best_practices_result if hasattr(result, 'best_practices_result') else {},
                'workflow_status': result.workflow_status if hasattr(result, 'workflow_status') else 'success',
                'errors': result.errors if hasattr(result, 'errors') else []
            }
        
        # Store in session with same structure for consistency
        # Convert to format matching /analyze endpoint
        formatted_response = {
            'vision_result': response_data.get('computer_vision', {}),
            'analyzer_result': response_data.get('agent_analysis', {}),
            'best_practices_result': response_data.get('best_practices', {}),
            'workflow_status': response_data.get('workflow_status', 'success'),
            'errors': response_data.get('errors', [])
        }
        
        # Store in global dict
        global analysis_results_store
        analysis_results_store['latest'] = formatted_response
        
        session['last_job_id'] = 'analyze-only'
        session['analysis_timestamp'] = datetime.now().isoformat()
        
        print(f"DEBUG /analyze-only: Stored in global store")
        print(f"DEBUG /analyze-only: Response keys: {formatted_response.keys()}")
        
        return jsonify(response_data)
    
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"ERROR in /analyze-only: {str(e)}")
        print(error_trace)
        return jsonify({
            'error': str(e),
            'traceback': error_trace
        }), 500


@app.route('/generate-iac', methods=['POST'])
def generate_iac():
    """Start background IAC generation from analyzer results."""
    global iac_jobs, last_terraform_project
    
    try:
        data = request.get_json()
        analyzer_result = data.get('analyzer_result')
        best_practices = data.get('best_practices')
        
        if not analyzer_result:
            return jsonify({'error': 'Missing analyzer_result'}), 400
        
        # Create job ID
        job_id = str(uuid.uuid4())
        iac_jobs[job_id] = {
            'status': 'pending',
            'result': None,
            'error': None,
            'project_path': None
        }
        
        # Start background thread
        def generate_in_background():
            try:
                iac_jobs[job_id]['status'] = 'running'
                
                config = Config.from_environment()
                orchestrator = WorkflowOrchestrator(config=config)
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_dir = os.path.join(app.config['TERRAFORM_FOLDER'], f'project_{timestamp}')
                
                result = orchestrator.execute_iac_generation(
                    analyzer_result,
                    best_practices=best_practices,
                    output_dir=output_dir
                )
                
                if result['success']:
                    iac_jobs[job_id]['status'] = 'completed'
                    iac_jobs[job_id]['result'] = result
                    iac_jobs[job_id]['project_path'] = result['project_path']
                    last_terraform_project = result['project_path']
                else:
                    iac_jobs[job_id]['status'] = 'failed'
                    iac_jobs[job_id]['error'] = result.get('error', 'Unknown error')
                    
            except Exception as e:
                import traceback
                iac_jobs[job_id]['status'] = 'failed'
                iac_jobs[job_id]['error'] = str(e)
                iac_jobs[job_id]['traceback'] = traceback.format_exc()
        
        thread = threading.Thread(target=generate_in_background, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'pending'
        })
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/iac-status/<job_id>', methods=['GET'])
def iac_status(job_id):
    """Check status of IAC generation job."""
    if job_id not in iac_jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = iac_jobs[job_id]
    
    response = {
        'job_id': job_id,
        'status': job['status']
    }
    
    if job['status'] == 'completed' and job['result']:
        response['terraform'] = {
            'generated': True,
            'project_path': job['project_path'],
            'files': job['result'].get('files', {}),
            'metadata': job['result'].get('metadata', {})
        }
    elif job['status'] == 'failed':
        response['error'] = job['error']
    
    return jsonify(response)


@app.route('/progress/<job_id>')
def progress_stream(job_id):
    """Server-Sent Events (SSE) endpoint for real-time progress updates."""
    
    def generate_events():
        """Generator function for SSE events"""
        # Create a queue for this job if it doesn't exist
        if job_id not in progress_queues:
            progress_queues[job_id] = queue.Queue(maxsize=100)
        
        job_queue = progress_queues[job_id]
        
        # Send initial connection event
        yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id})}\n\n"
        
        # Stream progress events
        timeout_counter = 0
        max_timeout = 300  # 5 minutes timeout
        
        while timeout_counter < max_timeout:
            try:
                # Wait for events with timeout
                event = job_queue.get(timeout=1)
                
                # Send the event to client
                yield f"data: {json.dumps(event)}\n\n"
                
                # Check if workflow is complete
                if event.get('type') == 'executor_complete' and event.get('step') == '4/4':
                    yield f"data: {json.dumps({'type': 'workflow_complete'})}\n\n"
                    break
                elif event.get('type') == 'executor_error':
                    yield f"data: {json.dumps({'type': 'workflow_error', 'error': event.get('error')})}\n\n"
                    break
                    
                timeout_counter = 0  # Reset timeout on activity
                
            except queue.Empty:
                # Send heartbeat to keep connection alive
                timeout_counter += 1
                yield f": heartbeat\n\n"
                continue
        
        # Cleanup
        if job_id in progress_queues:
            del progress_queues[job_id]
    
    return Response(generate_events(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/analyze', methods=['POST'])
def analyze():
    """Legacy endpoint - full workflow with blocking IAC generation."""
    global last_terraform_project, analysis_results_store
    
    with trace_operation("analyze_diagram", {"endpoint": "/analyze"}):
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF, BMP'}), 400
        
        # Check if user wants Terraform generation
        generate_terraform = request.form.get('generate_terraform', 'true').lower() == 'true'
    
    try:
        # Generate unique job ID for progress tracking
        job_id = str(uuid.uuid4())
        
        add_event("workflow_started", {"job_id": job_id, "filename": file.filename})
        set_attribute("job_id", job_id)
        set_attribute("generate_terraform", generate_terraform)
        
        # Save file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Initialize orchestrator
        orchestrator = WorkflowOrchestrator()
        
        # Execute workflow with job_id for progress tracking
        with trace_operation("execute_workflow", {"job_id": job_id}):
            result = orchestrator.execute_workflow(
                image_path=filepath,
                job_id=job_id
            )
        
        add_event("workflow_completed", {"job_id": job_id})
        
        # Debug logging
        print(f"=== APP.PY DEBUG ===")
        print(f"Result type: {type(result)}")
        print(f"Result: {result}")
        if hasattr(result, 'vision_result'):
            print(f"vision_result present: {bool(result.vision_result)}")
        if hasattr(result, 'analyzer_result'):
            print(f"analyzer_result present: {bool(result.analyzer_result)}")
        if hasattr(result, 'best_practices_result'):
            print(f"best_practices_result present: {bool(result.best_practices_result)}")
        print(f"===================")
        
        # Store project path for download
        if hasattr(result, 'terraform_path') and result.terraform_path:
            last_terraform_project = result.terraform_path
        
        # Convert result to dict for easier access
        if hasattr(result, 'model_dump'):
            result_dict = result.model_dump()
        elif hasattr(result, 'dict'):
            result_dict = result.dict()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {}
        
        # Debug: Log Terraform result
        terraform_result = result.terraform_result if hasattr(result, 'terraform_result') else result_dict.get('terraform_result')
        print(f"DEBUG: Terraform result keys: {terraform_result.keys() if terraform_result else 'None'}")
        if terraform_result:
            for key, value in terraform_result.items():
                print(f"DEBUG: {key} length: {len(value) if value else 0}")
        
        # Return comprehensive results
        response = {
            'success': result.workflow_status == 'success' if hasattr(result, 'workflow_status') else result_dict.get('workflow_status') == 'success',
            'job_id': job_id,
            'workflow_status': result.workflow_status if hasattr(result, 'workflow_status') else result_dict.get('workflow_status', 'unknown'),
            'vision_result': result.vision_result if hasattr(result, 'vision_result') else result_dict.get('vision_result', {}),
            'analyzer_result': result.analyzer_result if hasattr(result, 'analyzer_result') else result_dict.get('analyzer_result', {}),
            'best_practices_result': result.best_practices_result if hasattr(result, 'best_practices_result') else result_dict.get('best_practices_result', {}),
            'terraform': {
                'generated': bool(terraform_result),
                'project_path': result.terraform_path if hasattr(result, 'terraform_path') else result_dict.get('terraform_path'),
                'files': terraform_result or {}
            },
            'infracost': {
                'cost_estimate': result.cost_estimate if hasattr(result, 'cost_estimate') else result_dict.get('cost_estimate', {}),
                'cost_report': result.cost_report if hasattr(result, 'cost_report') else result_dict.get('cost_report', '')
            },
            'errors': result.errors if hasattr(result, 'errors') else result_dict.get('errors', [])
        }
        
        # IMPORTANT: Store in global dict (more reliable for complex objects)
        # Also store job_id in session to track which result belongs to this user
        global analysis_results_store
        analysis_results_store['latest'] = response  # Simple key for single-user demo
        
        session['last_job_id'] = job_id
        session['analysis_timestamp'] = datetime.now().isoformat()
        
        print(f"DEBUG /analyze: Stored in global store with job_id: {job_id}")
        print(f"DEBUG /analyze: Response keys: {response.keys()}")
        print(f"DEBUG /analyze: best_practices_result present: {'best_practices_result' in response}")
        print(f"DEBUG /analyze: Session job_id: {session.get('last_job_id')}")
        
        # Clean up uploaded file
        os.remove(filepath)
        
        return jsonify(response)
    
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/download-terraform', methods=['GET'])
def download_terraform():
    """Download the last generated Terraform project as a ZIP file."""
    global last_terraform_project
    
    if not last_terraform_project or not os.path.exists(last_terraform_project):
        return jsonify({'error': 'No Terraform project available for download'}), 404
    
    try:
        # Create ZIP file
        project_name = Path(last_terraform_project).name
        zip_filename = f'{project_name}.zip'
        zip_path = os.path.join(app.config['TERRAFORM_FOLDER'], zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            project_path = Path(last_terraform_project)
            for file in project_path.iterdir():
                if file.is_file():
                    zipf.write(file, arcname=file.name)
        
        return send_file(
            zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_filename
        )
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/view-terraform/<filename>', methods=['GET'])
def view_terraform_file(filename):
    """View a specific Terraform file content."""
    global last_terraform_project
    
    if not last_terraform_project or not os.path.exists(last_terraform_project):
        return jsonify({'error': 'No Terraform project available'}), 404
    
    allowed_files = ['providers.tf', 'main.tf', 'variables.tf', 'outputs.tf', 'terraform.tfvars', 'README.md', 'metadata.json']
    
    if filename not in allowed_files:
        return jsonify({'error': 'Invalid file requested'}), 400
    
    try:
        file_path = os.path.join(last_terraform_project, filename)
        if not os.path.exists(file_path):
            return jsonify({'error': f'File {filename} not found'}), 404
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            'filename': filename,
            'content': content
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/best-practices')
def best_practices_page():
    """Render the best practices page."""
    return render_template('best_practices.html')


@app.route('/api/latest-best-practices', methods=['GET'])
def get_latest_best_practices():
    """Get the most recent best practices data from global store."""
    
    global analysis_results_store
    
    # Debug: Check what we have
    print(f"DEBUG: Global store keys: {list(analysis_results_store.keys())}")
    print(f"DEBUG: Session job_id: {session.get('last_job_id')}")
    
    # Retrieve from global store
    last_analysis_result = analysis_results_store.get('latest')
    
    if not last_analysis_result:
        return jsonify({'error': 'No analysis available. Please run an analysis first.'}), 404
    
    # Get data from response structure (matches /analyze endpoint)
    best_practices_result = last_analysis_result.get('best_practices_result', {})
    analyzer_result = last_analysis_result.get('analyzer_result', {})
    
    print(f"DEBUG: best_practices_result type: {type(best_practices_result)}")
    print(f"DEBUG: best_practices_result keys: {best_practices_result.keys() if isinstance(best_practices_result, dict) else 'Not a dict'}")
    print(f"DEBUG: analyzer_result keys: {analyzer_result.keys() if isinstance(analyzer_result, dict) else 'Not a dict'}")
    
    # More lenient check - allow if best_practices exists even with empty recommendations
    if not best_practices_result:
        return jsonify({'error': 'No best practices available. The analysis may not have completed successfully.'}), 404
    
    # Return in format expected by best_practices.html
    return jsonify({
        'success': True,
        'best_practices': best_practices_result,  # This contains service_recommendations, architecture_checklist, etc.
        'cloud_provider': analyzer_result.get('cloud_provider', 'Microsoft Azure'),
        'total_services': analyzer_result.get('total_services', 0),
        'azure_services': analyzer_result.get('azure_services', [])
    })


@app.route('/api/restore-session', methods=['GET'])
def restore_session():
    """Restore the last analysis session when returning to main page."""
    global analysis_results_store
    
    last_analysis_result = analysis_results_store.get('latest')
    
    if not last_analysis_result:
        return jsonify({'has_session': False})
    
    return jsonify({
        'has_session': True,
        'timestamp': session.get('analysis_timestamp'),
        'analyzer_result': last_analysis_result.get('analyzer_result'),
        'best_practices_result': last_analysis_result.get('best_practices_result'),
        'terraform': {
            'generated': bool(last_analysis_result.get('terraform')),
            'project_path': last_analysis_result.get('terraform', {}).get('project_path'),
            'files': last_analysis_result.get('terraform', {}).get('files', {})
        },
        'workflow_status': last_analysis_result.get('workflow_status'),
        'errors': last_analysis_result.get('errors', [])
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
