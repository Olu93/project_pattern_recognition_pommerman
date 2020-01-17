import datetime
import os
import platform
import random
from collections import deque
import time
import gym
import numpy as np
import tensorflow as tf
from tensorflow.keras import models, layers
import psutil
import pommerman
from pommerman import agents

### =========== HELPER FUNCTIONS =========== ###


def preprocess(img):
    return img/255

### =========== CREATE THE CNN =========== ###


def create_model(input_shape, action_space):
    input = layers.Input(input_shape, dtype=tf.float32)
    mask = layers.Input(action_space, dtype=tf.float32)

    with tf.name_scope("ConvGroup-1"):
        x = layers.Conv2D(16, (8, 8), strides=4, activation="relu")(input)
        # x = layers.MaxPooling2D((2, 2))(x)
        x = layers.BatchNormalization()(x)
        x = layers.Dropout(.4)(x)

    with tf.name_scope("ConvGroup-2"):
        x = layers.Conv2D(32, (4, 4), strides=2, activation="relu")(x)
        # x = layers.MaxPooling2D((2, 2))(x)
        x = layers.BatchNormalization()(x)
        x = layers.Dropout(.4)(x)

    with tf.name_scope("ConvGroup-3"):
        x = layers.Conv2D(32, (3, 3), activation="relu")(x)
        # # x = layers.MaxPooling2D((2, 2))(x)
        x = layers.BatchNormalization()(x)
        x = layers.Dropout(.4)(x)

    x = layers.Flatten()(x)

    with tf.name_scope("Value-Stream"):
        value_stream = layers.Dense(128, activation="relu")(x)
        value_out = layers.Dense(1)(value_stream)

    with tf.name_scope("Advantage-Stream"):
        advantage_stream = layers.Dense(128, activation="relu")(x)
        advantage_out = layers.Dense(action_space)(advantage_stream)

    with tf.name_scope("Q-Layer"):
        output = value_out + \
            tf.math.subtract(advantage_out, tf.reduce_mean(
                advantage_out, axis=1, keepdims=True))
        out_q_values = tf.multiply(output, mask)
    # out_q_values = tf.reshape(out_q_values, [1,-1])
    model = models.Model(inputs=[input, mask], outputs=out_q_values)
    model.compile(optimizer='rmsprop', loss='mean_squared_error')
    return model


def main():
    if platform.system() == 'Darwin':
        print("MacBook Pro user detected. U rule.")
        os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

    process = psutil.Process(os.getpid())

    # Create the environment
    agent_list = [
        agents.RandomAgent(),
        agents.SimpleAgent(),
        agents.SimpleAgent(),
        agents.SimpleAgent(),
    ]

    env = pommerman.make('PommeFFACompetition-v0',
                         agent_list, render_mode='human')

    # MARK: - Allowing to save the model
    now = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    checkpoint_path = os.path.join(
        ".",
        "models",
        now,
        "-{epoch:04d}.ckpt"
    )
    # MARK: - Log for tensorboard
    log_dir = os.path.join(
        "logs",
        now,
    )
    tensorflow_callback = tf.keras.callbacks.TensorBoard(
        log_dir=log_dir, profile_batch=5, histogram_freq=1)
    file_writer_rewards = tf.summary.create_file_writer(log_dir + "/metrics")

    ### =========== (HYPER)PARAMETERS AND VARIABLES =========== ###

    LIST_SIZE = 60000
    D = deque(maxlen=LIST_SIZE)
    DISCOUNT_RATE = 0.8
    TAU = 0
    MAX_TAU = 2000
    ACTION_SPACE = env.action_space.n
    TIME_CHANNELS_SIZE = 1
    SKIP_FRAMES = 1
    INPUT_SHAPE = list(env.get_observation_space()) + [TIME_CHANNELS_SIZE]
    STATE_SHAPE = INPUT_SHAPE[:2] + [TIME_CHANNELS_SIZE+1]
    BATCH_SIZE = 32
    N = BATCH_SIZE
    N_EPISODES = 1000
    Q_MASK_SHAPE = (BATCH_SIZE, ACTION_SPACE)
    EXPLORATION_BASE = 1.02
    EXPLORATION_RATE = 1
    MINIMAL_EXPLORATION_RATE = 0.01

    print(f"Pixel space of the game {INPUT_SHAPE}")
    approximator_model = create_model(INPUT_SHAPE, ACTION_SPACE)
    target_model = create_model(INPUT_SHAPE, ACTION_SPACE)

    # ===== INITIALISATION ======
    frame_cnt = 0
    prev_lives = 5
    acc_nonzeros = []
    acc_actions = []

    print("Running the init")
    for n in range(N):
        state_obs = env.reset()
        done = False
        while not done:
            actions_all_agents = env.act(state_obs)
            state_obs, reward, done, info, pixels = env.step2(
                actions_all_agents)

            D.append((preprocess(pixels), reward[0], actions_all_agents[0]))
        print('Init episode {} finished'.format(n))

    for episode in range(N_EPISODES):
        start_time = time.time()

        if TAU >= MAX_TAU:
            TAU = 0
            # Copy the weights from policy model to target model
            target_model.set_weights(approximator_model.get_weights())
            print("===> Updated weights")

        # EXPLORATION_RATE = np.power(EXPLORATION_BASE, -episode) if EXPLORATION_RATE > MINIMAL_EXPLORATION_RATE else MINIMAL_EXPLORATION_RATE
        EXPLORATION_RATE = 1 - \
            (episode*1/N_EPISODES) if EXPLORATION_RATE > MINIMAL_EXPLORATION_RATE else MINIMAL_EXPLORATION_RATE

        print(
            f"Running episode {episode} with exploration rate: {EXPLORATION_RATE}")

        # Intial step for the episode
        state_obs = env.reset()
        actions = env.act(state_obs)
        initial_observation, reward, done, info, pixels = env.step2(
            actions, render=True)

        state = preprocess(pixels)

        done = False

        # next_state = initial_state.copy()  # To remove all the information of the last episode

        episode_rewards = []
        frame_cnt = 0

        while not done:
            # https://danieltakeshi.github.io/2016/11/25/frame-skipping-and-preprocessing-for-deep-q-networks-on-atari-2600-games/
            frame_cnt += 1
            TAU += 1

            actions_all_agents = env.act(state_obs)

            if not random.choices((True, False), (EXPLORATION_RATE, 1 - EXPLORATION_RATE))[0]:
                # Greedy action
                init_mask = tf.ones([1, ACTION_SPACE])
                init_state = state
                q_values = approximator_model.predict(
                    [tf.reshape(init_state, [1] + INPUT_SHAPE), init_mask])
                action = np.argmax(q_values)

                actions_all_agents[0] = action

            state_obs, reward, done, info, pixels = env.step2(
                actions_all_agents)

            if done:
                last_action = "Place bomb" if actions_all_agents[0] == 5 else "Something else"
                print(f"Last action: {last_action}")

            episode_rewards.append(reward[0])
            D.append((preprocess(pixels), reward[0], actions_all_agents[0]))

        print(f"Number of frames in memory {len(D)}")
        experience_batch = random.sample(D, k=BATCH_SIZE)

        set_of_batch_states = tf.constant([exp[0] for exp in experience_batch])

        # Gather actions for each batch item
        set_of_batch_actions = tf.one_hot(
            [exp[2] for exp in experience_batch], ACTION_SPACE)
        set_of_batch_states = tf.cast(tf.reshape(
            set_of_batch_states, set_of_batch_states.shape + [1]), dtype=tf.float32)

        # Maybe unnecessary - We are using the double q mask instead.
        next_q_mask = tf.ones([BATCH_SIZE, ACTION_SPACE])
        double_q_mask = tf.one_hot(tf.argmax(approximator_model.predict(
            [set_of_batch_states, next_q_mask]), axis=1), ACTION_SPACE)  # http://arxiv.org/abs/1509.06461
        next_q_values = tf.constant(target_model.predict(
            [set_of_batch_states, double_q_mask]))

        tmp_init_q_values = tf.constant(approximator_model.predict(
            [set_of_batch_states, set_of_batch_actions]))

        # Gather rewards for each batch item
        set_of_batch_rewards = tf.constant(
            [exp[1] for exp in experience_batch], dtype=next_q_values.dtype)
        episode_nonzero_reward_states = (
            tf.math.count_nonzero(set_of_batch_rewards)/BATCH_SIZE)*100
        print(
            f"Number of information yielding states: {episode_nonzero_reward_states}")

        next_q = set_of_batch_rewards + \
            (DISCOUNT_RATE * tf.reduce_max(next_q_values, axis=1))

        # print("------"*15)
        # tf.print(next_q)
        # tf.print(tf.reduce_max(tmp_init_q_values, axis=1))
        # tf.print(
        #     tf.square(next_q-tf.reduce_max(tmp_init_q_values, axis=1)))
        # somethingLoss = tf.square(
        #     next_q-tf.reduce_max(tmp_init_q_values, axis=1))
        # tf.print(tf.reduce_sum(somethingLoss)/BATCH_SIZE)
        # print("------"*15)

        history = approximator_model.fit(
            [set_of_batch_states, set_of_batch_actions], next_q, verbose=1, callbacks=[tensorflow_callback])

        # Wrap up
        loss = history.history.get("loss", [0])[0]
        time_end = np.round(time.time() - start_time, 2)
        memory_usage = process.memory_info().rss
        print(f"Current memory consumption is {memory_usage}")
        print(
            f"Loss of episode {episode} is {loss} and took {time_end} seconds")
        with file_writer_rewards.as_default():
            tf.summary.scalar('episode_rewards', np.sum(
                episode_rewards), step=episode)
            tf.summary.scalar('episode_loss', loss, step=episode)
            tf.summary.scalar('episode_time_in_secs', time_end, step=episode)
            tf.summary.scalar('episode_nr_frames', frame_cnt, step=episode)
            tf.summary.scalar('episode_exploration_rate',
                              EXPLORATION_RATE, step=episode)
            tf.summary.scalar('episode_mem_usage', memory_usage, step=episode)
            tf.summary.scalar('episode_frames_per_sec', np.round(
                frame_cnt/time_end, 2), step=episode)
            tf.summary.histogram('q-values', next_q_values, step=episode)
            if (episode+1) % 5 == 0:
                acc_nonzeros.append(episode_nonzero_reward_states)
                tf.summary.histogram(
                    'episode_nonzero_reward_states', acc_nonzeros, step=(episode+1)//5)
            else:
                acc_nonzeros.append(episode_nonzero_reward_states)
        if (episode+1) % 50 == 0:
            model_target_dir = checkpoint_path.format(epoch=episode)
            approximator_model.save_weights(model_target_dir)
            print(f"Model was saved under {model_target_dir}")

# TODO: [x] Simplify the loss function
# TODO: [x] Apply the reward
# TODO: [x] Rethink memory handling
# TODO: [x] Proper memory initialisation
# TODO: [ ] Refactoring and restructuring


if __name__ == "__main__":
    main()
