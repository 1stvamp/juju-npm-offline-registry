from contextlib import contextmanager
from os import makedirs
from os.path import join
from shutil import chown
from subprocess import check_call

from charmhelpers.core import hookenv
from charmhelpers.core.host import adduser, restart_on_change, user_exists
from charmhelpers.core.templating import render
from charms.layer.nodejs import npm, node_dist_dir
from charms.reactive import when, set_state
from nginxlib import configure_site


USER = 'npm-offline-registry'
SYSTEMD_PATH = '/lib/systemd/system/npm-offline-registry.service'
UPSTART_PATH = '/etc/init/npm-offline-registry.conf'


@contextmanager
def maintenance_status(begin, end):
    try:
        hookenv.status_set('maintenance', begin)
        yield
    finally:
        hookenv.status_set('maintenance', end)


def get_user():
    if not user_exists(USER):
        adduser(USER, shell='/bin/false', system_user=True)
    return USER


def get_cache(base_path, user):
    cache_path = join(base_path, 'cache-data')
    makedirs(cache_path, exist_ok=True)
    chown(cache_path, user=user)
    return cache_path


def get_bin_path(base_path):
    return join(base_path, 'node_modules/.bin/npm-offline-registry')


def get_local_registry_or_host(uri=False):
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
     return check_call('ps -p1 | grep -q systemd', shell=True)


@when('nodejs.available', 'config.changed.version')
def install():
    version = hookenv.config('version')
    if version:
        pkg = 'npm-offline-registry@{}'.format(version)
        with maintenance_status('Installing {} with NPM'.format(pkg),
                                '{} installed'.format(pkg)):
            npm('install {}'.format(pkg))
            set_state('npm-offline-registry.installed')


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

    with maintenance_status('Generating upstart configuration',
                            'upstart configuration generated'):
        config_ctx = hookenv.config()
        config_ctx['working_dir'] = dist_dir
        config_ctx['user'] = user
        config_ctx['npm_cache_path'] = get_cache(dist_dir, user)
        config_ctx['bin_path'] = get_bin_path(dist_dir)
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
                          '-c', '1:', '-a', 'bin/npm-offline-registry'],
                         name='check_npm-offline-registry_procs',
                         description='Verify at least one npm-offline-registry'
                                     'process is running',
                         context=hookenv.config('nagios_context'),
                         unit= hookenv.local_unit())


@when('nginx.available')
def configure_nginx():
    config_ctx = {
        'server_name': get_local_registry_or_host(),
        'cache_dir': get_cache(node_dist_dir(), get_user()),
    }
    configure_site('npm-offline-rgistry', 'vhost.conf.j2', **config_ctx)
