from contextlib import contextmanager
from os import makedirs
from os.path import dirname, exists, join
from shutil import chown
from subprocess import check_call
from tempfile import NamedTemporaryFile

from charmhelpers import fetch
from charmhelpers.core import hookenv
from charmhelpers.core.host import (
    adduser,
    restart_on_change,
    service_restart,
    user_exists,
)
from charmhelpers.core.templating import render
from charmhelpers.payload.execd import execd_run
from charms.layer.nodejs import npm, node_dist_dir
from charms.reactive import only_once, set_state, when
from nginxlib import configure_site


USER = 'npm-offline-registry'
SYSTEMD_PATH = '/lib/systemd/system/npm-offline-registry.service'
UPSTART_PATH = '/etc/init/npm-offline-registry.conf'


@contextmanager
def maintenance_status(begin, end):
    """ContextManager to easilly wrap an action in maintenance status messages.
    """
    try:
        hookenv.status_set('maintenance', begin)
        yield
    finally:
        hookenv.status_set('maintenance', end)


def get_user():
    """Helper to ensure our user exists and return the username.
    """
    if not user_exists(USER):
        adduser(USER, shell='/bin/false', system_user=True)
    return USER


def get_cache(base_path, user):
    """Helper to get the use provided cache dir or the vendored path.
    """
    cache_path = hookenv.config('cache_dir')
    if not cache_path:
        cache_path = join(base_path, 'cache-data')
    return cache_path


def get_bin_path(base_path):
    """Helper that returns the correct path to npm-offline-registry,
    regardless of if it was installed with NPM or from a repository.
    """
    www_path = join(base_path, 'bin/www')
    if exists(www_path):
        p = www_path
    else:
        p = join(base_path, 'node_modules/.bin/npm-offline-registry')

    return p


def get_local_registry_or_host(uri=False):
    """Helper to give us either the local_registry config, or use the NGinX
    host config as backup.
    If ``uri`` is `True` the returned value will include the HTTP/HTTPS URI
    prefix.
    """
    local_cache = hookenv.config('local_cache')

    if local_cache:
        if '://' not in local_cache:
            return local_cache
    else:
        local_cache = 'http://{}'.format(hookenv.config('host'))

    local_cache = local_cache.rstrip('/')
    if uri:
        return local_cache

    return local_cache.split('://')[1]


def is_systemd():
    """Helper that returns `True` if the PID1 init system is systemd.
    """
    return check_call('ps -p1 | grep -q systemd', shell=True) == 0


@when('nodejs.available', 'config.changed.version')
def install():
    version = hookenv.config('version')
    src_path = join(dirname(dirname(__file__)), 'npm-offline-registry-src')

    if exists(src_path):
        install_from_charm_dir(src_path)
    elif version:
        # npm-offline-registry relies on wget for non-isolated fetches from
        # upstream registry, just in case let's always install it
        fetch.apt_install(fetch.filter_installed_packages(['wget']))

        repo = hookenv.config('repo')
        if repo:
            install_from_repo(repo, version)
        else:
            install_with_npm(version)


def install_with_npm(version):
    pkg = 'npm-offline-registry@{}'.format(version)

    with maintenance_status('Installing {} with NPM'.format(pkg),
                            '{} installed'.format(pkg)):
        npm('install {}'.format(pkg))

        service_restart('npm-offline-registry')
        set_state('npm-offline-registry.installed')


def install_from_charm_dir(src_path):
    pkg = 'npm-offline-registry'
    dist_dir = node_dist_dir()
    wildcard_src = join(src_path, '*')
    wildcard_dest = join(dist_dir.rstrip('.'), '*')

    with maintenance_status('Installing {} from charm directory'.format(pkg),
                            '{} installed'.format(pkg)):
        check_call(['rm', '-rf', wildcard_dest])
        check_call('cp -R {} {}'.format(wildcard_src, dist_dir), shell=True)

        # If the vendored payload did not bundle the Node.js dependencies for
        # npm-offline-registry, then let's try to install them with NPM
        if not exists(join(dist_dir, 'node_modules')):
            npm('install')

    service_restart('npm-offline-registry')
    set_state('npm-offline-registry.installed')


def install_from_repo(repo, version):
    pkg = 'npm-offline-registry@{}'.format(version)
    dist_dir = node_dist_dir()
    apt_pkg_map = {
        'git': 'git-core',
        'hg': 'mercurial',
        'svn': 'subversion',
    }
    repo_types = ('git', 'hg', 'svn')

    with maintenance_status('Installing {} from {}'.format(pkg, repo),
                            '{} installed'.format(pkg)):
        repo_type = hookenv.config('repo_type').lower()

        if repo_type in repo_types:
            # Ensure we have the required underlying SCM installed firtst
            fetch.apt_install(
                fetch.filter_installed_packages([apt_pkg_map[repo_type]]))
            # We use the excellent peru to pull in builds from SCM repos
            # but it requires a pregenerated YAML file on disk
            with NamedTemporaryFile() as f:
                render(source='npm-offline-registry_peru.yaml.j2',
                    target=f.name,
                    context={
                        'url': repo,
                        'module': repo_type,
                        'revision': version,
                    })

                check_call(['sudo', 'su', '-s', '/bin/sh', '-', get_user(),
                            '-c',
                            ' '.join(('peru',
                                      '--file={}'.format(f.name),
                                      '--sync-dir={}'.format(dist_dir),
                                      'sync'))])

            # If the repo did not bundle the Node.js dependencies for
            # npm-offline-registry, then let's try to install them with NPM
            if not exists(join(dist_dir, 'node_modules')):
                npm('install')

            service_restart('npm-offline-registry')
            set_state('npm-offline-registry.installed')
        else:
            raise ValueError('Unknown repo_type "{}",not one of {}'.format(
                             repo_type, repo_types))



@when('config.changed', 'npm-offline-registry.installed')
@restart_on_change({
    SYSTEMD_PATH: ['npm-offline-registry'],
    UPSTART_PATH: ['npm-offline-registry'],
},
stopstart=True)
def configure():
    dist_dir = node_dist_dir()
    user = get_user()

    if is_systemd():
        conf_path = SYSTEMD_PATH
        template_type = 'systemd'
    else:
        conf_path = UPSTART_PATH
        template_type = 'upstart'

    with maintenance_status('Generating {} configuration'.format(
                                template_type),
                            'upstart configuration generated'):
        config_ctx = hookenv.config()
        config_ctx['working_dir'] = dist_dir
        config_ctx['user'] = user
        config_ctx['npm_cache_path'] = get_cache(dist_dir, user)
        config_ctx['bin_path'] = get_bin_path(dist_dir)
        config_ctx['enable_failover'] = str(
            config_ctx['enable_failover']).lower()
        config_ctx['local_registry_or_host_uri'] = get_local_registry_or_host(
            uri=True)

        render(source='npm-offline-registry_{}.j2'.format(template_type),
               target=conf_path,
               owner='root',
               perms=0o744,
               context=config_ctx)
        set_state('npm-offline-registry.available')


@when('local-monitors.available', 'nrpe-external-master.available',
      'npm-offline-registry.available')
def setup_nagios(nagios):
    with maintenance_status('Creating Nagios check', 'Nagios check created'):
        nagios.add_check(['/usr/lib/nagios/plugins/check_procs',
                          '-c', '1:', '-a', get_bin_path()],
                         name='check_npm-offline-registry_procs',
                         description='Verify at least one npm-offline-registry'
                                     'process is running',
                         context=hookenv.config('nagios_context'),
                         unit= hookenv.local_unit())


@when('nginx.available')
def configure_nginx():
    with maintenance_status('Generating NGinX configuration',
                            'NGinX configuration generated'):
        config_ctx = {
            'server_name': get_local_registry_or_host(),
            'cache_dir': get_cache(node_dist_dir(), get_user()),
        }
        configure_site('npm-offline-rgistry', 'vhost.conf.j2', **config_ctx)
        hookenv.open_port(hookenv.config('port'))


@when('nginx.available', 'website.available')
def configure_website(website):
        website.configure(port=hookenv.config('port'))


@hookenv.atstart
@only_once
def preinstall():
    with maintenance_status('Running preinstallation hooks',
                            'Preinstallation hooks finished'):
        execd_run('charm-pre-install', die_on_error=True)
