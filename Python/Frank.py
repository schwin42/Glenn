from __future__ import division

import gym
import numpy as np
import random
import tensorflow as tf
import tensorflow.contrib.slim as slim
#import matplotlib.pyplot as plt
#import scipy.misc
import os
#%matplotlib inline

env = gym.make("SpaceInvaders-v0")

class Qnetwork():
	def __init__(self,h_size):
		#The network recieves a frame from the game, flattened into an array.
		#It then resizes it and processes it through four convolutional layers.
		self.scalarInput =  tf.placeholder(shape=[None,INPUT_SIZE],dtype=tf.float32)
		self.imageIn = tf.reshape(self.scalarInput,shape=[-1,210,160,3])
		#self.imageIn = tf.placeholder(shape = [None, 210, 160, 3], dtype = tf.float32) #None here is batch size - number of images to process?
		print("imageIn: " + str(self.imageIn.get_shape()))
		self.conv1 = slim.conv2d( \
			inputs=self.imageIn,num_outputs=32,kernel_size=[8,8],stride=[4,4],padding='VALID', biases_initializer=None)
		print("conv1: " + str(self.conv1.get_shape()))
		self.conv2 = slim.conv2d( \
			inputs=self.conv1,num_outputs=64,kernel_size=[4,4],stride=[2,2],padding='VALID', biases_initializer=None)
		print("conv2: " + str(self.conv2.get_shape()))
		self.conv3 = slim.conv2d( \
			inputs=self.conv2,num_outputs=64,kernel_size=[3,3],stride=[2,2],padding='VALID', biases_initializer=None)
			#inputs=self.conv2,num_outputs=64,kernel_size=[3,3],stride=[1,1],padding='VALID', biases_initializer=None)

		print("conv3: " + str(self.conv3.get_shape()))
		self.conv4 = slim.conv2d( \
			inputs=self.conv3,num_outputs=h_size,kernel_size=[7,7],stride=[6,2],padding='VALID', biases_initializer=None)
		print("conv4: " + str(self.conv4.get_shape()))	
		#We take the output from the final convolutional layer and split it into separate advantage and value streams.
		self.streamAC,self.streamVC = tf.split(self.conv4,2,3) #Should be 1 x 1 x 1 256, but is 1 x 16 x 10 x 256
		print("streamAC", self.streamAC.get_shape())
		self.streamA = slim.flatten(self.streamAC)
		self.streamV = slim.flatten(self.streamVC)
		xavier_init = tf.contrib.layers.xavier_initializer() #Initializes weights proportionate to input layer
		
		#print("action space: " + str(env.action_space.n) + ", " + str(type(env.action_space.n)))
		self.AW = tf.Variable(xavier_init([h_size//2,env.action_space.n]))
		self.VW = tf.Variable(xavier_init([h_size//2,1]))
		self.Advantage = tf.matmul(self.streamA,self.AW) # 1 x 256 (H) * 256(H) x 6 (action_size)
		self.Value = tf.matmul(self.streamV,self.VW)
		
		#Then combine them together to get our final Q-values.
		self.Qout = self.Value + tf.subtract(self.Advantage,tf.reduce_mean(self.Advantage,axis=1,keep_dims=True))
		self.predict = tf.argmax(self.Qout,1)
		
		#Below we obtain the loss by taking the sum of squares difference between the target and prediction Q values.
		self.targetQ = tf.placeholder(shape=[None],dtype=tf.float32)
		self.actions = tf.placeholder(shape=[None],dtype=tf.int32)
		self.actions_onehot = tf.one_hot(self.actions,env.action_space.n,dtype=tf.float32)
		
		self.Q = tf.reduce_sum(tf.multiply(self.Qout, self.actions_onehot), axis=1)
		
		self.td_error = tf.square(self.targetQ - self.Q)
		self.loss = tf.reduce_mean(self.td_error)
		self.trainer = tf.train.AdamOptimizer(learning_rate=0.0001)
		self.updateModel = self.trainer.minimize(self.loss)
		
class experience_buffer():
	def __init__(self, buffer_size = 50000):
		self.buffer = []
		self.buffer_size = buffer_size
	
	def add(self,experience):
		if len(self.buffer) + len(experience) >= self.buffer_size:
			self.buffer[0:(len(experience)+len(self.buffer))-self.buffer_size] = []
		self.buffer.extend(experience)
			
	def sample(self,size):
		return np.reshape(np.array(random.sample(self.buffer,size)),[size,5])
	
def processState(states, size):
	return np.reshape(states,size)

def updateTargetGraph(tfVars,tau):
	total_vars = len(tfVars)
	op_holder = []
	for idx,var in enumerate(tfVars[0:total_vars//2]):
		op_holder.append(tfVars[idx+total_vars//2].assign((var.value()*tau) + ((1-tau)*tfVars[idx+total_vars//2].value())))
	return op_holder

def updateTarget(op_holder,sess):
	for op in op_holder:
		sess.run(op)
		
batch_size = 32 #How many experiences to use for each training step.
update_freq = 100 #How often to perform a training step.
y = .99 #Discount factor on the target Q-values
startE = 1 #Starting chance of random action
endE = 0.1 #Final chance of random action
annealing_steps = 10000. #How many steps of training to reduce startE to endE.
num_episodes = 10000 #How many episodes of game environment to train network with.
pre_train_steps = 10000 #How many steps of random actions before training begins.
max_epLength = 10000 #The max allowed length of our episode.
load_model = True #Whether to load a saved model.
path = "./SpaceInvaders" #The path to save our model to.
h_size = 512 #The size of the final convolutional layer before splitting it into Advantage and Value streams.
tau = 0.001 #Rate to update target network toward primary network

#New constants
INPUT_SIZE = 100800 #State size
SAVE_FREQUENCY = 10 #How many episodes to wait between saves
LOG_FREQUENCY = 10

tf.reset_default_graph()
mainQN = Qnetwork(h_size)
targetQN = Qnetwork(h_size)

init = tf.global_variables_initializer()

saver = tf.train.Saver()

trainables = tf.trainable_variables()

targetOps = updateTargetGraph(trainables,tau)

myBuffer = experience_buffer()

#Set the rate of random action decrease. 
e = startE
stepDrop = (startE - endE)/annealing_steps

#create lists to contain total rewards and steps per episode
jList = []
rList = []
total_steps = 0

#Make a path for our model to be saved in.
if not os.path.exists(path):
	os.makedirs(path)

with tf.Session() as sess:
	
	sess.run(init)
	if load_model == True:
		print('Loading Model...')
		ckpt = tf.train.get_checkpoint_state(path)
		saver.restore(sess,ckpt.model_checkpoint_path)
	for i in range(num_episodes):
		episodeBuffer = experience_buffer()
		#Reset environment and get first new observation
		s = env.reset()
		s = processState(s, INPUT_SIZE)
		d = False
		rAll = 0
		j = 0
		#The Q-Network
		while j < max_epLength: #If the agent takes longer than 200 moves to reach either of the blocks, end the trial.
			j+=1
			
			#Choose an action by greedily (with e chance of random action) from the Q-network
			if np.random.rand(1) < e or total_steps < pre_train_steps:
				a = np.random.randint(0,4)
			else:
				a = sess.run(mainQN.predict,feed_dict={mainQN.scalarInput:[s]})[0]
			s1,r,d, info = env.step(a) #Last arg is info, containing lives
			#print("info", info)
			lives = info['ale.lives']
			#print("lives", lives)
			if lives < 3:
				d = True
			#env.render()
			
			s1 = processState(s1, INPUT_SIZE)
			total_steps += 1
			episodeBuffer.add(np.reshape(np.array([s,a,r,s1,d]),[1,5])) #Save the experience to our episode buffer.
			
			if total_steps > pre_train_steps:
				if e > endE:
					e -= stepDrop
				
				if total_steps % (update_freq) == 0:
					trainBatch = myBuffer.sample(batch_size) #Get a random batch of experiences.
					#Below we perform the Double-DQN update to the target Q-values
					#print("train batch: ", trainBatch[:,3])
					#print("train batch rows: " + str(len(trainBatch[:,2])))
					#print("train batch columns: " + str(len(trainBatch[:,2][0])))
					
					
					#print("train batch rows: " + str(len(trainBatch[:,3])))
					#print("train batch columns: " + str(len(trainBatch[:,3][0])))
					Q1 = sess.run(mainQN.predict,feed_dict={mainQN.scalarInput:np.vstack(trainBatch[:,3])})
					Q2 = sess.run(targetQN.Qout,feed_dict={targetQN.scalarInput:np.vstack(trainBatch[:,3])})
					end_multiplier = -(trainBatch[:,4] - 1)
					doubleQ = Q2[range(batch_size),Q1]
					targetQ = trainBatch[:,2] + (y*doubleQ * end_multiplier)
					#Update the network with our target values.
					_ = sess.run(mainQN.updateModel, \
						feed_dict={mainQN.scalarInput:np.vstack(trainBatch[:,0]),mainQN.targetQ:targetQ, mainQN.actions:trainBatch[:,1]})
					
					updateTarget(targetOps,sess) #Update the target network toward the primary network.
			rAll += r
			s = s1
			
			if d == True:
				print("episode #" + str(i) + " - " + "reward: " + str(rAll) + ", steps: " + str(j))
				break
		
		myBuffer.add(episodeBuffer.buffer)
		jList.append(j)
		rList.append(rAll)
		#Periodically save the model. 
		if i % SAVE_FREQUENCY == 0:
			saver.save(sess,path+'/model-'+str(i)+'.ckpt')
			#print("Saved Model")
		if len(rList) % LOG_FREQUENCY == 0:
			print("Mean reward for " + str(i - SAVE_FREQUENCY) + " - " + str(i) + ": " + str(np.mean(rList[-SAVE_FREQUENCY:])))
	saver.save(sess,path+'/model-'+str(i)+'.ckpt')
#print("Percent of succesful episodes: " + str(sum(rList)/num_episodes) + "%")