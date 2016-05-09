from charms.nodejs import npm, node_dist_dir
from charms.reactive import when, set_state


@when('nodejs.available', 'config.version.changed')
def install_npm_offline_registry():
    npm('install', 'npm-offline-registry@{}'.format(hookenv.config('version')))
    set_state('npm-offline-registry.installed')


@when('npm-offline-registry.installed')
def start_npm_offline_registry():
    # npm-offline-registry
    pass
