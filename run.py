'''An example to show how to set up an pommerman game programmatically'''
import pommerman
from pommerman import agents
import time
from statistics import mean


def main():
    '''Simple function to bootstrap a game.

       Use this as an example to set up your training env.
    '''
    # Print all possible environments in the Pommerman registry
    print(pommerman.REGISTRY)

    # Create a set of agents (exactly four)
    agent_list = [
        agents.SimpleAgent(),
        agents.RandomAgent(),
        agents.SimpleAgent(),
        agents.RandomAgent(),
        # agents.DockerAgent("pommerman/simple-agent", port=12345),
    ]
    # Make the "Free-For-All" environment using the agent list
    env = pommerman.make('PommeFFACompetition-v0',
                         agent_list, render_mode='human')

    # Run the episodes just like OpenAI Gym
    for i_episode in range(20):

        state = env.reset()
        done = False

        while not done:
            actions = env.act(state)
            state, reward, done, info, pixels = env.step2(actions)
        print('Episode {} finished'.format(i_episode))
    env.close()


if __name__ == '__main__':
    main()
