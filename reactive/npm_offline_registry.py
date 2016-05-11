from contextlib import contextmanager
from os import makedirs
from os.path import join
from shutil import chown

from charmhelpers.core import hookenv
from charmhelpers.core.host import adduser, restart_on_change, user_exists
from charmhelpers.core.templating import render
from charms.layer.nodejs import npm, node_dist_dir
from charms.reactive import when, set_state


USER = 'npm-offline-registry'
SYSTEMD_PATH = '/lib/systemd/system/npm-offline-registry.service'


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
@restart_on_change({SYSTEMD_PATH: ['npm-offline-registry']}, stopstart=True)
def configure():
    dist_dir = node_dist_dir()
    user = get_user()

    with maintenance_status('Generating upstart configuration',
                            'upstart configuration generated'):
        config_ctx = hookenv.config()
        config_ctx['working_dir'] = dist_dir
        config_ctx['user'] = user
        config_ctx['npm_cache_path'] = get_cache(dist_dir, user)
        config_ctx['bin_path'] = get_bin_path(dist_dir)

        render(source='npm-offline-registry_systemd.j2',
               target=SYSTEMD_PATH,
               owner='root',
               perms=0o744,
               context=config_ctx)
