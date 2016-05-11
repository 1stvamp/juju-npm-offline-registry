from contextlib import contextmanager
from os import makedirs
from os.path import join
from shutil import chown

from charmhelpers.core import hookenv
from charmhelpers.core.host import adduser, restart_on_change, user_exists
from charms.layer.nodejs import npm, node_dist_dir
from charms.reactive import when, set_state


USER = 'npm-offline-registry'
UPSTART_PATH = '/etc/init/npm-offline-registry.conf'


def maintenance_status(msg):
    try:
        hookenv.status_set('maintenance', msg)
        yield
    finally:
        hookenv.status_unset('maintenance')


def get_user():
    if not user_exists(USER):
        adduser(USER, shell='/bin/false', system_user=True)
    return USER


def get_cache(base_path, user):
    cache_path = join(base_path, 'cache-data')
    makedirs(cache_path, exist_ok=True)
    chown(cache_path, user=user)
    return cache_path


def get_bin_path():
    return 'node_modules/.bin/npm-offline-registry'


@when('nodejs.available', 'config.changed.version')
def install():
    version = hookenv.config('version')
    if version:
        pkg = 'npm-offline-registry@{}'.format(version)
        with maintenance_status('Installing {} with NPM'.format(pkg)):
            npm('install {}'.format(pkg))
            set_state('npm-offline-registry.installed')


@when('config.changed', 'npm-offline-registry.installed')
@restart_on_change({UPSTART_PATH: ['npm-offline-registry']}, stopstart=True)
def configure():
    dist_dir = node_dist_dir()
    user = get_user()

    with maintenance_status('Generating upstart configuration'):
        config_ctx = hookenv.config()
        config_ctx['working_dir'] = dist_dir
        config_ctx['user'] = user
        config_ctx['npm_cache_path'] = get_cache(dist_dir, user)
        config_ctx['bin_path'] = get_bin_path()

        render(source='npm-offline-registry_upstart.j2',
               target=UPSTART_PATH,
               owner='root',
               perms=0o744,
               context=config_ctx)
