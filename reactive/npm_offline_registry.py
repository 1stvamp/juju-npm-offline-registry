from charmhelpers.core import hookenv
from charms.layer.nodejs import npm, node_dist_dir
from charms.reactive import when, set_state


@when('nodejs.available', 'config.changed.version')
def install_npm_offline_registry():
    version = hookenv.config('version')
    if version:
        npm('install npm-offline-registry@{}'.format(version))
        set_state('npm-offline-registry.installed')


@when('npm-offline-registry.installed')
def start_npm_offline_registry():
    # npm-offline-registry
    pass
