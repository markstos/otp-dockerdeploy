from fabric.context_managers import settings, prefix, cd, lcd, shell_env
from fabric.contrib.project import rsync_project
from fabric.decorators import task, roles
from fabric.operations import local, prompt, run, put
from fabric.state import env
from fabric.tasks import execute
import time
from dockerfabric import tasks as docker


# see https://github.com/merll/docker-fabric
env.docker_tunnel_local_port = 22024  # or any other available port above 1024 of your choice
# see http://stackoverflow.com/a/28382014
env.use_ssh_config = True

running_locally = lambda : not env.hosts or len(env.hosts) == 0

def xrun(cmd, *args, **kwargs):
    if running_locally():
        local(cmd, *args, **kwargs)
    else:
        run(cmd, *args, **kwargs)
        
@task 
def build_builder():
    """
    build the builder
    """
    xrun('docker build -t opentripplanner:builder builder')
    xrun('docker images | grep opentripplanner')

@task    
def build_server():
    """
    build the server
    """
    xrun('docker build -t opentripplanner:server server')
    xrun('docker images | grep opentripplanner')

@task    
def build_nginx():
    """
    build the nginx image
    """
    xrun('docker build -t opentripplanner:nginx nginx ')
    xrun('docker images | grep opentripplanner')
    
@task 
def go(name=None, port=None, urls=None, params=None, build=False, 
       router=False, headers=None, useragent=None):
    """
    run the server, build the graph, restart the server
    
    :param name: the name of the image, defaults to 'otpserver'
    :param port: the host port to serve at, defaults to 80
    :param urls: list of URL files to download (gtfs, pdx)
    :param params: list of parameters to run the server 
    """
    params = params or ''
    assert urls, "need at least one gtfs file (checkout http://www.gtfs-data-exchange.com/agencies)"
    opts = {
        'name' : name or 'otpserver',
        'urls' : ' '.join(urls.split(',')),
        'params' : ' '.join(params.split(',')), 
        'port' : port or 80,
        'router' : router or 'default',
        'headers' : headers.split(',') if headers else '', 
        'useragent' : useragent,
    }
    if build:
        if not running_locally():
            target = './otp-dockerdeploy'
            tmptar = '/tmp/otp-dockerdeploy.tgz'
            run('mkdir -p %s' % target)
            local('tar -czf %s --exclude .git .' % tmptar)
            put(tmptar, tmptar)
            run('tar -C %s -xzf %s' % (target, tmptar))
            run('docker ps')
            with cd(target):
                execute(build_builder)
                execute(build_server)
        else:
            execute(build_builder)
            execute(build_server)
    cmd_rmserver = (
      'docker rm -f {name} 2>&1 >/dev/null'
    ).format(**opts)
    cmd_server = (
     'docker run '
     ' -p {port}:8080 -d'
     ' --name {name}'
     ' opentripplanner:server '
     ' --router {router} --server '    
     #' --longDistance '     
    ).format(**opts)
    useragent = opts.get('useragent')
    headers = opts.get('headers')
    opts['_headers'] = [' -H %s' % h for h in headers] if headers else ''
    opts['_useragent'] = ('-U %s' % useragent) if useragent else ''
    cmd_builder = (
      'docker run --volumes-from {name}'
     ' opentripplanner:builder '
     ' -u "{urls}" -e "{params}"'
     ' {_useragent} {_headers} ' 
    ).format(**opts)
    cmd_restart = (
      'docker restart {name}'
    ).format(**opts)
    cmd_serverlog = (
       'docker ps | grep {name} | cut -c 1-10 | xargs docker logs'
    ).format(**opts)
    # be nice and tell what we're doing
    print "[INFO] Running with options %s" % opts
    # run the server (delete existing server first)
    with settings(warn_only=True):
        xrun(cmd_rmserver)
    xrun(cmd_server)
    time.sleep(10)
    xrun(cmd_serverlog)
    # build the graph
    xrun(cmd_builder)
    # restart the server
    xrun(cmd_restart)
    time.sleep(10)
    xrun(cmd_serverlog)
    # report success
    print "[INFO] server {name} running at http://localhost:{port}".format(**opts)
    
@task
def dockerrm(images=None, containers=None):
    """
    mass remove images and containers
    """
    prompt('Are you sure? Press Ctrl-C otherwise.')
    xrun('docker ps --all | grep Exited | cut -c1-19 | xargs -L1 docker rm')
    xrun('docker images | grep "6 months" | cut -c 35-65 | xargs -L1 docker rmi')
    
@task 
def enter(name=None):
    xrun('PID=$(docker inspect --format {{.State.Pid}} %s) && nsenter --target $PID --mount' % name)