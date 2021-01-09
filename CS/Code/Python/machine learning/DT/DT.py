import tensorflow as tf

from gym import envs
envs_specs=envs.registry.all()
env_ids=[envs_specs.id for envs_specs in envs_specs]
print(env_ids)
zero_tsr=tf.zeros([3,3])
