from os.path import join

from charmhelpers.core import hookenv
from charmhelpers.core.host import adduser, restart_on_change, user_exists
from charms.layer.nodejs import npm, node_dist_dir
from charms.reactive import when, set_state, when_file_changed


USER = 'npm-offline-registry'
UPSTART_PATH = '/etc/init/npm-offline-registry.conf'


def ensure_user_exists():
    if not user_exists(USER):
        adduser(USER, shell='/bin/false', system_user=True)


def get_bin_path():
    return 'node_modules/.bin/npm-offline-registry'


@when('nodejs.available', 'config.changed.version')
def install():
    version = hookenv.config('version')
    if version:
        pkg = 'npm-offline-registry@{}'.format(version)
        hookenv.status_set('maintenance', 'Installing {} with NPM'.format(pkg))

        npm('install {}'.format(pkg))
        set_state('npm-offline-registry.installed')


@when('config.changed', 'npm-offline-registry.installed')
@restart_on_change({UPSTART_PATH: ['npm-offline-registry']}, stopstart=True)
def configure():
    ensure_user_exists()
    dist_dir = node_dist_dir()

    hookenv.status_set('maintenance', 'Generating upstart configuration')
    config_ctx = hookenv.config()
    config_ctx['user'] = USER
    config_ctx['working_dir'] = dist_dir
    config_ctx['bin_path'] = get_bin_path()
    config_ctx['npm_cache_path'] = join(dist_dir, 'cache-data')

    render(source='npm-offline-registry_upstart.j2',
           target=UPSTART_PATH,
           owner='root',
           perms=0o744,
           context=config_ctx)
