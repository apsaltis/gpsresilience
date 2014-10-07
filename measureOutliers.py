# -*- coding: utf-8 -*-
"""
Created on Wed Sep 24 12:34:53 2014

@author: brian
"""
import numpy
from numpy import matrix, transpose, diag
import os, csv
from collections import defaultdict
from multiprocessing import Pool

from mahalanobis import *
from eventDetection import *
from lof import *
from tools import *

NUM_PROCESSORS = 8


#Reads time-series pace data from a file, and sorts it into a convenient format.
#Arguments:
	#dirName - the directory which contains time-series features (produced by extractGridFeatures.py)
#Returns:  (pace_timeseries, var_timeseries, count_timeseries, pace_grouped).  Breakdown:
	#pace_timeseries - a dictionary which maps (date, hour, weekday) to the corresponding average pace vector (average pace of each trip type)
	#var_timeseries - a dictionary which maps (date, hour, weekday) to the corresponding pace variance vector (variance of paces of each trip type)
	#count_timeseries - a dictionary which maps (date, hour, weekday) to the corresponding count vector (number of occurrences of each trip type)
	#pace_grouped - a dictionary which maps (weekday, hour) to the list of corresponding pace vectors
	#		for example, ("Wednesday", 5) maps to the list of all pace vectors that occured on a Wednesday at 5am.
def readPaceData(dirName):
	logMsg("Reading files from " + dirName + " ...")
	#Create filenames
	paceFileName = os.path.join(dirName, "pace_features.csv")

	
	#Initialize dictionaries	
	pace_timeseries = {}
	pace_grouped = defaultdict(list)
	dates_grouped = defaultdict(list)
	
	#Read the pace file
	r = csv.reader(open(paceFileName, "r"))
	colIds = getHeaderIds(r.next())
	
	#Read the file line by line
	for line in r:
		#Extract info
		#First 3 columns
		date = line[colIds["Date"]]
		hour = int(line[colIds["Hour"]])
		weekday = line[colIds["Weekday"]]
		
		#The rest of the columns contain paces
		paces = map(float, line[3:])
		
		#Convert to numpy column vector
		v = transpose(matrix(paces))
		#Save vector in the timeseries
		pace_timeseries[(date, hour, weekday)] = v
		
		#If there is no missing data, save the vector into the group
		if(allNonzero(v)):
			pace_grouped[(weekday, hour)].append(v)
			dates_grouped[(weekday, hour)].append(date)

	
	#return time series and grouped data
	return (pace_timeseries, pace_grouped, dates_grouped)





#Reads the time-series global pace from a file and sorts it into a convenient format
#Arguments:
	#dirName - the directory which contains time-series features (produced by extractGridFeatures.py)
#Returns: - a dictionary which maps (date, hour, weekday) to the average pace of all taxis in that timeslice
def readGlobalPace(dirName):
	paceFileName = os.path.join(dirName, "global_features.csv")
	
	#Read the pace file
	r = csv.reader(open(paceFileName, "r"))
	colIds = getHeaderIds(r.next())
	
	pace_timeseries = {}

		
	
	for line in r:
		#Extract info
		#First 3 columns
		date = line[colIds["Date"]]
		hour = int(line[colIds["Hour"]])
		weekday = line[colIds["Weekday"]]
		#Last 16 columns
		pace = float(line[colIds["Pace"]])
		

		#Save vector in the timeseries and the group
		pace_timeseries[(date, hour, weekday)] = pace

	return pace_timeseries
	
#Computes the outlier scores for all of the mean pace vectors in a given weekday/hour pair (for example Wednesdays at 3pm)
#Many of these can be run in parallel
#params:
	#A tuple (paceGroup, dateGroup, hour, weekday) - see groupIterator()
#returns:
	#A list of tuples, each of which contain various types of outlier scores for each date
def processGroup((paceGroup, dateGroup, hour, weekday)):
	logMsg("Processing " + weekday + " " + str(hour))
	
	#Compute mahalanobis outlier scores
	mahals = computeMahalanobisDistances(paceGroup)
	
	#compute local outlier factors with various k parameters
	lofs1 = getLocalOutlierFactors(paceGroup, 1)
	lofs3 = getLocalOutlierFactors(paceGroup, 3)
	lofs5 = getLocalOutlierFactors(paceGroup, 5)
	lofs10 = getLocalOutlierFactors(paceGroup, 10)
	lofs20 = getLocalOutlierFactors(paceGroup, 20)
	lofs30 = getLocalOutlierFactors(paceGroup, 30)
	lofs50 = getLocalOutlierFactors(paceGroup, 50)

	#A dictionary which maps (date, hour, weekday), to an entry
	#An entry is a tuple that contains various types of outlier scores
	scores = {}
	for i in range(len(paceGroup)):
		entry = (mahals[i], lofs1[i], lofs3[i], lofs5[i], lofs10[i], lofs20[i], lofs30[i], lofs50[i])
		scores[dateGroup[i], hour, weekday] = entry
	
	#Return the scores
	return scores

#An iterator which supplies inputs to processGroup()
#Each input contains a set of mean pace vectors, and some extra time info
#params:
	#pace_grouped - Lists of vectors, indexed by weekday/hour pair - see readPaceData()
	#date_grouped - Date strings, indexd by weekday/hour pair - see readPaceData()
def groupIterator(pace_grouped, dates_grouped):
	#Iterate through weekday/hour pairs
	for (weekday, hour) in pace_grouped:
		#Grab the list of vectors
		paceGroup = pace_grouped[weekday, hour]
		#grab the list of dates
		dateGroup = dates_grouped[weekday, hour]
		#Each output contains these lists, as well as the hour and day of week
		yield (paceGroup, dateGroup, hour, weekday)

#Merges many group scores - see the output of processGroup() - into one
#params:
	#outputList - a list of dictionaries, each of which map weekday/hour pairs to entries
	#Each element of the list is an output of processGroup()
#return:
	#a single dictionary which maps weekday/hour pairs to entries
def reduceOutputs(outputList):
	scores = {}
	for score in outputList:
		scores.update(score)
	return scores
	

#Generates time-series log-likelihood values
#Similar to generateTimeSeries(), but LEAVES OUT the current observation when computing the probability
#These describe how likely or unlikely the state of the city is, given the distribution of "similar"
# days (same hour and day of week) but not today.
#Params:
	#inDir - the directory which contains the time-series feature files (CSV format)
	#returns - no return value, but saves files into results/...
def generateTimeSeriesLeave1(inDir):
	numpy.set_printoptions(linewidth=1000, precision=4)
	
	#Read the time-series data from the file
	logMsg("Reading files...")
	(pace_timeseries, pace_grouped, dates_grouped) = readPaceData(inDir)

	#Also get global pace information
	global_pace_timeseries = readGlobalPace(inDir)
	(expected_pace_timeseries, sd_pace_timeseries) = getExpectedPace(global_pace_timeseries)

	logMsg("Starting processes")

	pool = Pool(NUM_PROCESSORS) #Prepare for parallel processing
	gIter = groupIterator(pace_grouped, dates_grouped) #Iterator breaks the data into groups
	
	outputList = pool.map(processGroup, gIter) #Run all of the groups, using as much parallel computing as possible

	logMsg("Merging output")
	#Merge outputs from all of the threads
	outlierScores = reduceOutputs(outputList)

	
	logMsg("Writing file")
	#Output to file
	scoreWriter = csv.writer(open("results/outlier_scores.csv", "w"))
	scoreWriter.writerow(['date','hour','weekday', 'mahal', 'lof1', 'lof3', 'lof5', 'lof10', 'lof20', 'lof30', 'lof50' ,'global_pace', 'expected_pace', 'sd_pace'])
	
	
	for (date, hour, weekday) in sorted(outlierScores):
		gl_pace = global_pace_timeseries[(date, hour, weekday)]
		exp_pace = expected_pace_timeseries[(date, hour, weekday)]
		sd_pace = sd_pace_timeseries[(date, hour, weekday)]
		
		(scores) = outlierScores[date, hour, weekday]
		
		scoreWriter.writerow([date, hour, weekday] + list(scores) + [gl_pace, exp_pace, sd_pace])

	logMsg("Done.")

if(__name__=="__main__"):
	generateTimeSeriesLeave1("4year_features")