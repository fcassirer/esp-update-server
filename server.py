from datetime import datetime
from flask import Flask, request, render_template, flash, redirect, url_for, send_from_directory, Response, make_response
import subprocess
import signal
from packaging import version
import re
import time
import os
import yaml
import psutil

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler, WatchedFileHandler

__author__ = 'Kristian Stobbe'
__copyright__ = 'Copyright 2019, K. Stobbe'
__credits__ = ['Kristian Stobbe']
__license__ = 'MIT'
__version__ = '1.1.0'
__maintainer__ = 'Kristian Stobbe'
__email__ = 'mail@kstobbe.dk'
__status__ = 'Production'

ALLOWED_EXTENSIONS = set(['bin'])
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = './bin'
app.config['SECRET_KEY'] = 'Kri57i4n570bb33r3nF1ink3rFyr'
if os.environ.get("ESP_CONFIG"):
  app.config.from_envvar('ESP_CONFIG')
PLATFORMS_YAML = app.config['UPLOAD_FOLDER'] + '/platforms.yml'

#
# Create named rotating log files for the incoming /log POSTs from various
#  endpoints (ESP8266 instances etc).
#

log_handlers = {}
log_lastbuffer = {}
maxlogsize = 4 * 1000000 # 4MB
tsafe_vars = { 'ftpid': None }
ota_selected = "__NONE__"

def logit(ident,msg):

  logid = ident.lower()
  lfilename = 'remotelogs/{}.log'.format(logid)

  # Do what a WatchedFileHandler() would if we could stack them ...
  try:
    stat = os.stat(lfilename)
  except FileNotFoundError as e:
    if logid in log_handlers:
      log_event("file {} not found, resetting logger".format(lfilename))
      for h in log_handlers[logid].handlers[:]:
          h.close()
          log_handlers[logid].removeHandler(h)
      del log_handlers[logid]

  if logid not in log_handlers:
    try:
      formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
      logger = logging.getLogger(logid)
      logger.setLevel(logging.INFO)

      comm='''
      handler = WatchedFileHandler(lfilename,mode='a',delay=True)
      handler.setFormatter(formatter)
      logger.addHandler(handler)

      handler = RotatingFileHandler(lfilename,maxBytes=maxlogsize, backupCount=5)
      handler.setFormatter(formatter)
      logger.addHandler(handler)
      '''

      handler = TimedRotatingFileHandler(lfilename,when="midnight", interval=1)
      handler.setFormatter(formatter)
      logger.addHandler(handler)

      log_handlers[logid] = logger
      log_lastbuffer[logid] = ""
      log_event("Created handler for {}".format(logid))
    except Exception as e:
      log_event("Could not create logger '{}', e={}".format(logid,e))
      return None

  log_lastbuffer[logid] += msg
  if msg[-1] == '\n':
    log_handlers[logid].info(msg.strip('\n'))
    log_lastbuffer[logid] = ""
  return logid

def log_event(msg):
    st = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
    print(st + ' ' + msg)


def allowed_ext(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def load_yaml():
    platforms = None
    try:
        with open(PLATFORMS_YAML, 'r') as stream:
            try:
                platforms = yaml.load(stream, Loader=yaml.FullLoader)
            except yaml.YAMLError as err:
                flash(err)
    except:
        flash('Error: File not found.')

    #  Now convert oldstyle platforms to the new format, not necessary on new runs
    if platforms:
      for key in platforms:
        if 'whitelist' in platforms[key]:
          # Old style, convert to more PC
          platforms['accesslist'] = platforms['whitelist']
          del platforms['whitelist']
        if 'accesslist' in platforms[key] and isinstance(platforms[key]['accesslist'],list):
          accesslist = platforms[key]['accesslist']
          platforms[key]['accesslist'] = {}
          for mac in accesslist:
            platforms[key]['accesslist'][mac] = {}

    return platforms

def save_yaml(platforms):
    try:
        with open(PLATFORMS_YAML, 'w') as outfile:
            yaml.dump(platforms, outfile, default_flow_style=False)
            return True
    except:
        flash('Error: Data not saved.')
    return False

def spawn_frontail(url_path,logname):
    global frontails_pid
    kill_frontail()
    log_event("starting frontail using url={}".format(url_path))
    ft = subprocess.Popen(['frontail','--url-path',url_path,'--theme','dark',logname],
                          start_new_session=True)
    time.sleep(2)
    tsafe_vars['ftpid'] = ft.pid
    log_event("Frontail pid: {}".format(ft.pid))
    return ft.pid

def kill_frontail(pid=None):
    frontails_pid = tsafe_vars['ftpid']
    log_event("Killing frontail, pid={}".format(frontails_pid))
    if frontails_pid:
      try:
        os.kill(frontails_pid,signal.SIGKILL)
        tsafe_vars['ftpid'] = None
      except ProcessLookupError:
        pass
    return

@app.context_processor
def utility_processor():
    def format_mac(mac):
        return ':'.join(mac[i:i+2] for i in range(0,12,2))
    return dict(format_mac=format_mac)


def parse_device_details(request):
  __dev = request.args.get('dev', default=None)
  __mac = None
  __ver = request.args.get('ver', default=None)

  if __dev:
    __dev = __dev.lower()

    for h in request.headers.keys():
      if h.upper().endswith("STA-MAC"):
        __mac = request.headers.get(h,default=None)
        break

    if __mac:
      __mac = str(re.sub(r'[^0-9A-fa-f]+', '', __mac.lower()))
    else:
      log_event("WARN: request made without known headers.")

    log_event("INFO: Dev: {} Ver: {} Mac: {}".format(__dev, __ver, __mac))

  return [__dev, __ver, __mac]

@app.route('/update', methods=['GET', 'POST'])
def update():
    __error = 400
    platforms = load_yaml()
    log_event("Req hdrs: \n{}".format(request.headers))
    __dev, __ver, __mac = parse_device_details(request)
    if __dev and __mac and __ver:
        if platforms:
            if __dev in platforms.keys():
                if __mac in platforms[__dev]['accesslist']:
                    if version.parse(__ver) < version.parse(platforms[__dev]['version']):
                        if os.path.isfile(app.config['UPLOAD_FOLDER'] + '/' + platforms[__dev]['file']):
                            platforms[__dev]['downloads'] += 1
                            save_yaml(platforms)
                            return send_from_directory(directory=app.config['UPLOAD_FOLDER'], filename=platforms[__dev]['file'],
                                                       as_attachment=True, mimetype='application/octet-stream',
                                                       attachment_filename=platforms[__dev]['file'])
                    else:
                        log_event("INFO: No update needed.")
                        return 'No update needed.', 304
                else:
                    log_event("ERROR: Device not accesslisted.")
                    return 'Error: Device not accesslisted.', 400
            else:
                log_event("ERROR: Unknown platform.")
                return 'Error: Unknown platform.', 400
        else:
            log_event("ERROR: Create platforms before updating.")
            return 'Error: Create platforms before updating.', 500
    log_event("ERROR: Invalid parameters.")
    return 'Error: Invalid parameters.', 400


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    platforms = load_yaml()
    if platforms and request.method == 'POST':
        if 'file' not in request.files:
            flash('Error: No file selected.')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Error: No file selected.')
            return redirect(request.url)
        if file and allowed_ext(file.filename):
            data = file.read()
            for __dev in platforms.keys():
                if re.search(__dev.encode('UTF-8'), data, re.IGNORECASE):
                    m = re.search(b'v\d+\.\d+\.\d+', data)
                    if m:
                        __ver = m.group()[1:].decode('utf-8')
                        if (platforms[__dev]['version'] is None) or (platforms[__dev]['version'] and version.parse(platforms[__dev]['version']) < version.parse(__ver)):
                            old_file = platforms[__dev]['file']
                            filename = __dev + '_' + __ver.replace('.', '_') + '.bin'
                            platforms[__dev]['version'] = __ver
                            platforms[__dev]['downloads'] = 0
                            platforms[__dev]['file'] = filename
                            platforms[__dev]['uploaded'] = datetime.now().strftime('%Y-%m-%d')
                            file.seek(0)
                            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                            file.close()
                            if save_yaml(platforms):
                                # Only delete old file after YAML file is updated.
                                if old_file:
                                    try:
                                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old_file))
                                    except:
                                        flash('Error: Removing old file failed.')
                                flash('Success: File uploaded.')
                            else:
                                flash('Error: Could not save file.')
                            return redirect(url_for('index'))
                        else:
                            flash('Error: Version must increase. File not uploaded.')
                            return redirect(request.url)
                    else:
                        flash('Error: No version found in file. File not uploaded.')
                        return redirect(request.url)
            flash('Error: No known platform name found in file. File not uploaded.')
            return redirect(request.url)
        else:
            flash('Error: File type not allowed.')
            return redirect(request.url)
    if platforms:
        return render_template('upload.html')
    else:
        return render_template('status.html', platforms=platforms, logs=log_handlers.keys())


@app.route('/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        if not request.form['name']:
            flash('Error: Invalid name.')
        else:
            platforms = load_yaml()
            if not platforms:
                platforms = dict()
            platforms[request.form['name'].lower()] = {'version': None,
                           'file': None,
                           'uploaded': None,
                           'downloads': 0,
                           'otaargs': None,
                           'accesslist': {}}
            if save_yaml(platforms):
                flash('Success: Platform created.')
            else:
                flash('Error: Could not save file.')
            return render_template('status.html', platforms=platforms, logs=log_handlers.keys())
        return redirect(request.url)
    return render_template('create.html')


@app.route('/delete', methods=['GET', 'POST'])
def delete():
    if request.method == 'POST':
        if not request.form['name']:
            flash('Error: Invalid name.')
        else:
            platforms = load_yaml()
            if platforms and request.form['name'] in platforms.keys():
                old_file = platforms[request.form['name']]['file']
                del platforms[request.form['name']]
                if save_yaml(platforms):
                    flash('Success: Platform deleted.')
                else:
                    flash('Error: Could not save file.')
                # Only delete old file after YAML file is updated.
                if old_file:
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old_file))
                    except:
                        flash('Error: Removing old file failed.')
            return render_template('status.html', platforms=platforms, logs=log_handlers.keys())
        return redirect(request.url)
    platforms = load_yaml()
    if platforms:
        return render_template('delete.html', names=platforms.keys())
    else:
        return render_template('status.html', platforms=platforms, logs=log_handlers.keys())


@app.route('/otaargs', methods=['GET', 'POST'])
def otaargs():
  platforms = load_yaml()
  global ota_selected
  if platforms:
    if request.method == 'POST':
      _device = request.form['device']
      ota_selected = _device
      if 'Update' in request.form['action']:
        # Ensure valid data.
        if _device and _device != '--' and request.form['jsonargs']:
          # Remove all unwanted characters.
          __deviceargs = str(request.form['jsonargs'])
          # Check length after clean-up makes up a full address.
          if len(__deviceargs) != 0:
            # All looks good - add to otaargs.
            platforms[_device]['otaargs'] = __deviceargs
            if save_yaml(platforms):
              flash('Success: Json args added.')
            else:
              flash('Error: Could not save file.')
          else:
            flash('Error: Json malformed.')
        else:
          flash('Error: No data entered.')
      elif 'Override' in request.form['action']:
        __macaddr = request.form['macaddr']
        ovalue = str(request.form['jsonargs'])
        if ovalue:
          platforms[_device]['accesslist'][__macaddr]['otaargs'] = ovalue
        else:
          if 'otaargs' in platforms[_device]['accesslist'][__macaddr]:
            del platforms[_device]['accesslist'][__macaddr]['otaargs']
        if save_yaml(platforms):
          flash('Success: Json args overridden for ' + __macaddr + '.')
        else:
          flash('Error: Could not save file.')
      else:
        flash('Error: Unknown action.')

      return render_template('otaargs.html', platforms=platforms,selected=ota_selected)
    else:
      #log_event("Req hdrs: {}".format(request.headers))
      __dev, __ver, __mac = parse_device_details(request)
      otaargs = None
      if __dev and __mac and __ver:
        log_event("INFO: Dev: " + __dev + "Ver: " + __ver)
        if platforms:
          if __dev in platforms.keys():
            if __mac in platforms[__dev]['accesslist']:
              log_event("override otaargs: {},{},{}".format(__dev,__ver,__mac))
              otaargs = platforms[__dev]['accesslist'][__mac].get('otaargs', platforms[__dev].get('otaargs', None))
        log_event("OTAARGS is {}".format(otaargs if otaargs else "None"))
        return make_response(otaargs,200)
      else:
        return render_template('otaargs.html', platforms=platforms,selected=ota_selected)
  else:
    return render_template('status.html', platforms=platforms, logs=log_handlers.keys())


@app.route('/accesslist', methods=['GET', 'POST'])
def accesslist():
    platforms = load_yaml()
    if platforms and request.method == 'POST':
        if 'Add' in request.form['action']:
            # Ensure valid data.
            if request.form['device'] and request.form['device'] != '--' and request.form['macaddr']:
                # Remove all unwanted characters.
                __mac = str(re.sub(r'[^0-9A-Fa-f]+', '', request.form['macaddr']).lower())
                # Check length after clean-up makes up a full address.
                if len(__mac) == 12:
                    # Check that address is not already on a accesslist.
                    print(platforms.values())
                    for value in platforms.values():
                        if value['accesslist'] and __mac in value['accesslist']:
                            flash('Error: Address already on a accesslist.')
                            return render_template('accesslist.html', platforms=platforms)
                    # All looks good - add to accesslist.
                    if not platforms[request.form['device']]['accesslist']:
                        platforms[request.form['device']]['accesslist'] = {}
                    platforms[request.form['device']]['accesslist'][__mac] = {}
                    if save_yaml(platforms):
                        flash('Success: Address added.')
                    else:
                        flash('Error: Could not save file.')
                else:
                    flash('Error: Address malformed.')
            else:
                flash('Error: No data entered.')
        elif 'Remove' in request.form['action']:
            platforms[request.form['device']]['accesslist'].pop(str(request.form['macaddr']),None)
            if save_yaml(platforms):
                flash('Success: Address removed.')
            else:
                flash('Error: Could not save file.')
        else:
            flash('Error: Unknown action.')

    if platforms:
        return render_template('accesslist.html', platforms=platforms)
    else:
        return render_template('status.html', platforms=platforms,logs=log_handlers.keys())

@app.route('/log', methods=['GET', 'POST'])
def debuglog():
    msg = request.get_data().decode("utf-8")
    ident = request.args.get('id', default="Debug")
    #log_event("({}): {}".format(ident,msg.strip('\n')))
    logit(ident,msg)
    return ident

@app.route('/webconsole', methods=['GET', 'POST'])
def webconsole():
  platforms = load_yaml()
  lname = request.args.get('log', default=None)
  if lname == None:
    return render_template('webconsole.html', platforms=platforms,logs=log_handlers.keys())

  lfile = None
  if lname in log_handlers:
    paths = []
    for handler in log_handlers[lname].handlers:
      if isinstance(handler, logging.FileHandler):
        lfile = handler.baseFilename
        log_event("Path: {}".format(lfile))

    log_event("Log found: {} for {}".format(lname,lfile))
  else:
    flash('Could not find log file for "{}"'.format(lname))
    return make_response('not found',404)

  frontail_url = "http://0.0.0.0:9001/{}".format(lname)
  spawn_frontail("/"+lname,lfile)
  log_event("log={}, url={}".format(lname,frontail_url))
  return render_template('logging.html', log=lname, frontail_url=frontail_url)

@app.route('/endlogger', methods=['GET'])
def end_logger():
  log_event("Killing fronttail ...")
  kill_frontail()
  log_event("loggers = {}".format(log_handlers.keys()))
  return make_response('ok', 200)

@app.route('/')
def index():
    platforms = load_yaml()
    return render_template('status.html', platforms=platforms, logs=log_handlers.keys())

if __name__ == '__main__':
    platforms = load_yaml()
    for p in platforms.keys():
      logit(p,"ESP Server Restart\n")
    app.run(host='0.0.0.0', port=int('5000'), debug=True)
