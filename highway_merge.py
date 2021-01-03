#!/usr/bin/env python3
# -*- coding: utf8

# highway_merge.py
# Replace OSM highways with NVDB (and Elveg)
# Usage: python highway_merge.py [command] [input_osm.osm] [input_nvdb.osm]
# Commands: - replace: Merge all existing OSM highways with NVDB
#			- offset: Include all NVDB highways above an certain average offset
#			- new: Include only NVDB highways not found in OSM
#			- tag: Update OSM highways with attributes from NVDB (maxspeed, name etc)
# Resulting file will be written to a new version of input file


import sys
import time
import math
import json
from xml.etree import ElementTree


version = "1.1.0"

debug = False      # True will provide extra keys in OSM file
merge_all = False  # True will try to merge from OSM even if NVDB way already matched

margin = 25       # Meters of tolarance for matching nodes
margin_new = 8    # Meters of tolerance for matching nodes, for "new" command
min_margin = 5    # Minimum average distance in meters for matching ways (used with "offset" command to filter large offsets)
match_factor = 5  # Max times longer/shorter matches
min_nodes = 2     # Min number of nodes in a way to be matched

# Do not merge OSM ways with the folowing highway categories
avoid_highway = ["path", "bus_stop", "rest_area", "platform", "construction", "proposed"]  # "motorway", "motorway_link"

# Do not merge OSM ways with the following keys
avoid_tags = ["area", "railway", "piste:type", "snowmobile", "turn:lanes", "turn:lanes:forward", "turn:lanes:backward", \
			 "destination", "destination:forward", "destination:backward", "destination:ref", "destination:ref:forward", "destination:ref:backward", \
			 "destination:symbol", "destination:symbol:forward", "destination:symbol:backward", "mtb:scale", "class:bicycle:mtb"]

# Overwrite with the following tags from NVDB when merging ways
avoid_merge = ["ref", "name", "maxspeed", "oneway", "junction", "foot", "bridge", "tunnel", "layer", "source"]

# Do not consider OSM highways of the following types when updating tags
avoid_highway_tags = ["cycleway", "footway", "steps"]

# Overwrite with the following tags from NVDB when updating tags in OSM
merge_tags = ["ref", "name", "maxspeed", "maxheight", "bridge", "tunnel", "layer"]

# Only consider the following highway categories when merging (leave empty [] to merge all)
replace_highway = []
#replace_highway = ["motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link", "primary_link", "secondary_link"]
#replace_highway = ["primary", "secondary", "primary_link", "secondary_link"]

# Output message

def message (line):

	sys.stdout.write (line)
	sys.stdout.flush()


# Compute approximation of distance between two coordinates, in meters
# Works for short distances

def distance(n1_lat, n1_lon, n2_lat, n2_lon):

	lon1, lat1, lon2, lat2 = map(math.radians, [n1_lon, n1_lat, n2_lon, n2_lat])
	x = (lon2 - lon1) * math.cos( 0.5*(lat2+lat1) )
	y = lat2 - lat1
	return 6371000 * math.sqrt( x*x + y*y )


# Main program

if __name__ == '__main__':

	# Read all data into memory

	start_time = time.time()
	
	if len(sys.argv) == 4 and sys.argv[1].lower() in ["-new", "-offset", "-replace", "-tag"]:
		command = sys.argv[1].lower().strip("-")
		filename_osm = sys.argv[2]
		filename_nvdb = sys.argv[3]
	else:
		message ("Please include 1) '-new'/'-offset'/'-replace'/'-tag' 2) OSM file and 3) NVDB file as parameters\n")
		sys.exit()

	message ("\nReading files '%s' and '%s' ..." % (filename_osm, filename_nvdb))

	tree_osm = ElementTree.parse(filename_osm)
	root_osm = tree_osm.getroot()

	tree_nvdb = ElementTree.parse(filename_nvdb)
	root_nvdb = tree_nvdb.getroot()

	from_ways = {}
	to_nodes = []
	all_nodes = {}


	# Prepare nodes

	message ("\nLoad nodes ...")

	nodes_osm = {}
	for node in root_osm.iter("node"):
		if not("action" in node.attrib and node.attrib['action'] == "delete"):
			nodes_osm[ node.attrib['id'] ] = {
				'index': node,
				'used': 0,
				'lat': float(node.attrib['lat']),
				'lon': float(node.attrib['lon'])
			}
			for tag in node.iter("tag"):
				if tag.attrib['k'] == "created_by":
					node.remove(tag)
					node.set("action", "modify")

	nodes_nvdb = {}
	for node in root_nvdb.iter("node"):
		nodes_nvdb[ node.attrib['id'] ] = {
			'index': node,
			'used': 0,
			'lat': float(node.attrib['lat']),
			'lon': float(node.attrib['lon'])
		}

	message (" %i OSM nodes, %i NVDB nodes" % (len(nodes_osm), len(nodes_nvdb)))


	# Determine bounding box and length of OSM ways

	message ("\nLoad ways ...")

	count_osm = 0
	count_osm_roads = 0
	ways_osm = {}

	for way in root_osm.iter("way"):
		count_osm += 1
		way_id = way.attrib['id']

		length = 0
		nodes = []
		highway = None
		incomplete = False
		avoid_match = False
		min_lat = 0.0
		min_lon = 0.0
		max_lat = 0.0
		max_lon = 0.0

		for tag in way.iter("tag"):
			osm_tag = tag.attrib['k']
			if osm_tag in avoid_tags:
				avoid_match = True
			if osm_tag == "highway":
				highway = tag.attrib['v']
				if highway not in avoid_highway:
					count_osm_roads += 1
				else:
					avoid_match = True

		for node in way.iter("nd"):
			node_id = node.attrib['ref']
			if node_id in nodes_osm:
				nodes_osm[ node_id ]['used'] += 1
			elif not("action" in node.attrib and node.attrib['action'] == "delete"):
				incomplete = True

		if "action" in way.attrib and way.attrib['action'] == "delete":
			incomplete = True

		if not incomplete:
			node_tag = way.find("nd")
			node_id = node_tag.attrib['ref']

			min_lat = nodes_osm[ node_id ]['lat']
			min_lon = nodes_osm[ node_id ]['lon']
			max_lat = min_lat
			max_lon = min_lon

			prev_lat = min_lat
			prev_lon = min_lon

			for node in way.iter("nd"):
				if not("action" in node.attrib and node.attrib['action'] == "delete"):
					node_id = node.attrib['ref']

					length += distance(prev_lat, prev_lon, nodes_osm[node_id]['lat'], nodes_osm[node_id]['lon'])
					prev_lat = nodes_osm[node_id]['lat']
					prev_lon = nodes_osm[node_id]['lon']

					nodes.append(node_id)

					min_lat = min(min_lat, prev_lat)
					min_lon = min(min_lon, prev_lon)
					max_lat = max(max_lat, prev_lat)
					max_lon = max(max_lon, prev_lon)

		ways_osm[ way_id ] = {
			'index': way,
			'highway': highway,
			'incomplete': incomplete,
			'avoid': avoid_match,
			'min_lat': min_lat - margin / 111500.0,
			'max_lat': max_lat + margin / 111500.0,
			'min_lon': min_lon - margin / (math.cos(math.radians(min_lat)) * 111320.0),
			'max_lon': max_lon + margin / (math.cos(math.radians(max_lat)) * 111320.0),
			'length': length,
			'nodes': nodes,
			'tags': {}
		}

	for relation in root_osm.iter("relation"):
		for member in relation.iter("member"):
			if member.attrib['type'] == "node" and member.attrib['ref'] in nodes_osm:
				nodes_osm[ member.attrib['ref'] ]['used'] += 1

	message (" %i OSM ways (%i roads)" % (count_osm, count_osm_roads))


	# Determine bounding box and length of NVDB ways

	count_nvdb = 0
	ways_nvdb = {}

	for way in root_nvdb.iter('way'):
		count_nvdb += 1
		node_tag = way.find("nd")
		node_ref = node_tag.attrib['ref']

		min_lat = nodes_nvdb[ node_ref ]['lat']
		min_lon = nodes_nvdb[ node_ref ]['lon']
		max_lat = min_lat
		max_lon = min_lon

		prev_lat = min_lat
		prev_lon = min_lon
		length = 0
		nodes = []

		for node in way.iter("nd"):
			node_id = node.attrib['ref']

			length += distance(prev_lat, prev_lon, nodes_nvdb[node_id]['lat'], nodes_nvdb[node_id]['lon'])
			prev_lat = nodes_nvdb[node_id]['lat']
			prev_lon = nodes_nvdb[node_id]['lon']

			nodes.append(node_id)

			min_lat = min(min_lat, prev_lat)
			min_lon = min(min_lon, prev_lon)
			max_lat = max(max_lat, prev_lat)
			max_lon = max(max_lon, prev_lon)

		highway_tag = way.find("tag[@k='highway']")
		if highway_tag != None:
			highway = highway_tag.attrib['v']
		else:
			highway = ""

		ways_nvdb[ way.attrib['id'] ] = {
			'index': way,
			'highway': highway,
			'missing': False,
			'min_lat': min_lat - margin / 111500.0,
			'max_lat': max_lat + margin / 111500.0,
			'min_lon': min_lon - margin / (math.cos(math.radians(min_lat)) * 111320.0),
			'max_lon': max_lon + margin / (math.cos(math.radians(max_lat)) * 111320.0),
			'length': length,
			'nodes': nodes
		}			

	message (", %i NVDB ways" % count_nvdb)


	# Merge NVDB and OSM higways

	message ("\nMatch ways ...\n")

	if command in ["replace", "offset"]:

		count = count_osm_roads
		count_swap = 0
		total_distance = 0

		for osm_id, osm_way in iter(ways_osm.items()):
			if not osm_way['incomplete'] and not osm_way['avoid'] and osm_way['highway'] != None and \
				(not replace_highway or osm_way['highway'] in replace_highway):
				message ("\r%i " % count)
				count -= 1

				best_id = None
				best_distance = 99999.0

				for nvdb_id, nvdb_way in iter(ways_nvdb.items()):
					if ("osm_id" not in nvdb_way or merge_all) and \
						(not replace_highway or nvdb_way['highway'] in replace_highway) and \
						not (nvdb_way['highway'] in ["cycleway", "footway"] and osm_way['highway'] not in ["cycleway", "footway", "track"]) and \
						not (nvdb_way['highway'] not in ["cycleway", "footway"] and osm_way['highway'] in ["cycleway", "footway"]) and \
						nvdb_way['min_lat'] <= osm_way['max_lat'] and nvdb_way['max_lat'] >= osm_way['min_lat'] and \
						nvdb_way['min_lon'] <= osm_way['max_lon'] and nvdb_way['max_lon'] >= osm_way['min_lon'] and \
						osm_way['length'] < match_factor * nvdb_way['length'] and \
						nvdb_way['length'] < match_factor * osm_way['length']:

						way_distance = 0.0
						count_distance = 0
						match_nodes = []

						for node_osm in osm_way['nodes']:
							min_node_distance = margin
							for node_nvdb in nvdb_way['nodes']:
								node_distance = distance(nodes_osm[node_osm]['lat'], nodes_osm[node_osm]['lon'], \
															nodes_nvdb[node_nvdb]['lat'], nodes_nvdb[node_nvdb]['lon'])
								if node_distance < min_node_distance:
									min_node_distance = node_distance
									min_node_ref = node_nvdb

							if min_node_distance < margin:
								count_distance += 1
								way_distance += min_node_distance
								if min_node_ref not in match_nodes:
									match_nodes.append(min_node_ref)

						if count_distance >= min_nodes and way_distance / count_distance < best_distance:
#						if count_distance >= min_nodes and count_distance > best_distance:

							match_length = 0
							prev_lat = nodes_nvdb[match_nodes[0]]['lat']
							prev_lon = nodes_nvdb[match_nodes[0]]['lon']
							for node in match_nodes[1:]:
								if node in nodes_nvdb:
									match_length += distance(prev_lat, prev_lon, nodes_nvdb[node]['lat'], nodes_nvdb[node]['lon'])
									prev_lat = nodes_nvdb[node]['lat']
									prev_lon = nodes_nvdb[node]['lon']

							if nvdb_way['length'] < match_factor * match_length:
								best_id = nvdb_id
								best_distance = way_distance / count_distance
#								best_distance = count_distance

				if best_id != None and (command == "replace" or best_distance > min_margin):
					count_swap += 1
					total_distance += best_distance
					if "osm_id" not in ways_nvdb[ best_id ]:
						ways_osm[ osm_id ]['nvdb_id'] = best_id
						ways_nvdb[ best_id ]['osm_id'] = osm_id
						ways_nvdb[ best_id ]['swap_no'] = count_swap  # Debug
						ways_nvdb[ best_id ]['distance'] = best_distance  # Debug
					elif merge_all:
						ways_osm[ osm_id ]['remove'] = True

		message ("\r%i highways matched, %i not matched" % (count_swap, count_osm_roads - count_swap))
		message ("\n%i missing ways added from NVDB" % (count_nvdb - count_swap))
		message ("\nAverage offset: %.1f m" % (total_distance / count_swap))


	# Identify missing NVDB highways

	elif command == "new":

		count = count_nvdb
		count_missing = 0

		for nvdb_id, nvdb_way in iter(ways_nvdb.items()):
			message ("\r%i " % count)
			count -= 1

			best_id = None
			best_distance = 99999.0

			for osm_id, osm_way in iter(ways_osm.items()):
				if not osm_way['incomplete'] and osm_way['highway'] != None and osm_way['highway'] not in avoid_highway and \
					not (nvdb_way['highway'] in ["cycleway", "footway"] and osm_way['highway'] not in ["cycleway", "footway", "track"]) and \
					not (nvdb_way['highway'] not in ["cycleway", "footway"] and osm_way['highway'] in ["cycleway", "footway"]) and \
					osm_way['min_lat'] <= nvdb_way['max_lat'] and osm_way['max_lat'] >= nvdb_way['min_lat'] and \
					osm_way['min_lon'] <= nvdb_way['max_lon'] and osm_way['max_lon'] >= nvdb_way['min_lon']:

					way_distance = 0.0
					count_distance = 0
					match_nodes = []

					for node_osm in osm_way['nodes']:
						min_node_distance = margin_new
						for node_nvdb in nvdb_way['nodes']:
							node_distance = distance(nodes_osm[node_osm]['lat'], nodes_osm[node_osm]['lon'], \
														nodes_nvdb[node_nvdb]['lat'], nodes_nvdb[node_nvdb]['lon'])
							if node_distance < min_node_distance:
								min_node_distance = node_distance
								min_node_ref = node_nvdb

						if min_node_distance < margin_new:
							count_distance += 1
							way_distance += min_node_distance
							if min_node_ref not in match_nodes:
								match_nodes.append(min_node_ref)

					if count_distance >= min_nodes and way_distance / count_distance < best_distance:
						match_length = 0
						prev_lat = nodes_nvdb[match_nodes[0]]['lat']
						prev_lon = nodes_nvdb[match_nodes[0]]['lon']
						for node in match_nodes[1:]:
							if node in nodes_nvdb:
								match_length += distance(prev_lat, prev_lon, nodes_nvdb[node]['lat'], nodes_nvdb[node]['lon'])
								prev_lat = nodes_nvdb[node]['lat']
								prev_lon = nodes_nvdb[node]['lon']

						if nvdb_way['length'] < match_factor * match_length:
							best_id = nvdb_id
							best_distance = way_distance / count_distance
							break

#					if count_distance >= min_nodes and way_distance / count_distance < best_distance:
#						best_id = osm_id
#						best_distance = way_distance / count_distance
#						break

			if best_id == None:
				ways_nvdb[ nvdb_id ]['missing'] = True
				count_missing += 1

		message ("\r%i missing highways" % count_missing)


	# Replace supporting tags (maxspeed, name etc)

	else:  # tag

		count = count_osm_roads
		count_swap = 0
		total_distance = 0

		for osm_id, osm_way in iter(ways_osm.items()):
			if not osm_way['incomplete'] and not osm_way['avoid'] and osm_way['highway'] != None and osm_way['highway'] not in avoid_highway_tags:
				message ("\r%i " % count)
				count -= 1

				best_id = None
				best_distance = 99999.0
				best_length = 0

				for nvdb_id, nvdb_way in iter(ways_nvdb.items()):
					if nvdb_way['highway'] not in avoid_highway_tags and \
						not (nvdb_way['highway'] in ["cycleway", "footway"] and osm_way['highway'] not in ["cycleway", "footway", "track"]) and \
						not (nvdb_way['highway'] not in ["cycleway", "footway"] and osm_way['highway'] in ["cycleway", "footway"]) and \
						nvdb_way['min_lat'] <= osm_way['max_lat'] and nvdb_way['max_lat'] >= osm_way['min_lat'] and \
						nvdb_way['min_lon'] <= osm_way['max_lon'] and nvdb_way['max_lon'] >= osm_way['min_lon'] and \
						osm_way['length'] < match_factor * nvdb_way['length'] and \
						nvdb_way['length'] < match_factor * osm_way['length']:

						way_distance = 0.0
						count_distance = 0
						match_nodes = []

						for node_osm in osm_way['nodes']:
							min_node_distance = margin
							for node_nvdb in nvdb_way['nodes']:
								node_distance = distance(nodes_osm[node_osm]['lat'], nodes_osm[node_osm]['lon'], \
															nodes_nvdb[node_nvdb]['lat'], nodes_nvdb[node_nvdb]['lon'])
								if node_distance < min_node_distance:
									min_node_distance = node_distance
									min_node_ref = node_osm

							if min_node_distance < margin:
								count_distance += 1
								way_distance += min_node_distance
								if min_node_ref not in match_nodes:
									match_nodes.append(min_node_ref)

						if count_distance >= min_nodes and way_distance / count_distance < best_distance:

							match_length = 0
							prev_lat = nodes_osm[match_nodes[0]]['lat']
							prev_lon = nodes_osm[match_nodes[0]]['lon']
							for node in match_nodes[1:]:
								if node in nodes_osm:
									match_length += distance(prev_lat, prev_lon, nodes_osm[node]['lat'], nodes_osm[node]['lon'])
									prev_lat = nodes_osm[node]['lat']
									prev_lon = nodes_osm[node]['lon']

							if nvdb_way['length'] < match_factor * match_length:
								best_id = nvdb_id
								best_distance = way_distance / count_distance
								best_length = match_length

				if best_id != None:
					ways_osm[ osm_id ]['nvdb_id'] = best_id
					count_swap += 1
					ways_osm[ osm_id ]['swap_no'] = count_swap  # Debug
					ways_osm[ osm_id ]['distance'] = best_distance  # Debug

		message ("\r%i highways matched" % count_swap)	


	# Merge NVDB ways with OSM

	message ("\nTransfer elements ...")

	# Empty start for 'new'
	if command == "new":
		root_osm = ElementTree.Element("osm", version="0.6")
		tree_osm = ElementTree.ElementTree(root_osm)

	for way in root_osm.findall("way"):
		osm_id = way.attrib['id']

		# Replace geometry and tags

		if command == "replace" and "nvdb_id" in ways_osm[ osm_id ]:

			nvdb_id = ways_osm[ osm_id ]['nvdb_id'] 
			nvdb_way = ways_nvdb[ nvdb_id ]['index']

			for tag_osm in way.findall("tag"):
				if tag_osm.attrib['k'] in avoid_merge:
					way.remove(tag_osm)

			for tag_nvdb in nvdb_way.iter("tag"):
				tag_osm = way.find("tag[@k='%s']" % tag_nvdb.attrib['k'])
				if tag_nvdb.attrib['k'] == "highway":
					if tag_osm != None and tag_nvdb.attrib['v'] != tag_osm.attrib['v']:
						way.append(ElementTree.Element("tag", k="NVDB", v=tag_nvdb.attrib['v']))
				elif tag_osm != None:
					tag_osm.set("v", tag_nvdb.attrib['v'])
				else:
					way.append(ElementTree.Element("tag", k=tag_nvdb.attrib['k'], v=tag_nvdb.attrib['v']))

			if debug:
				way.append(ElementTree.Element("tag", k="OSMID", v=osm_id))
				way.append(ElementTree.Element("tag", k="SWAP", v=str(ways_nvdb[ nvdb_id ]['swap_no'])))
				way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(ways_nvdb[ nvdb_id ]['distance']))))

			for node in way.findall('nd'):
				nodes_osm[ node.attrib['ref'] ]['used'] -= 1
				way.remove(node)

			for node in nvdb_way.iter("nd"):
				nodes_nvdb[ node.attrib['ref'] ]['used'] += 1
				way.append(ElementTree.Element("nd", ref=node.attrib['ref']))

			way.set("action", "modify")

		# Remove way

		elif command == "replace" and "remove" in ways_osm[ osm_id ]:

			for node in way.findall('nd'):
				nodes_osm[ node.attrib['ref'] ]['used'] -= 1
				way.remove(node)

			way.set("action", "delete")

		# Regplace tags only

		elif command == "tag" and "nvdb_id" in ways_osm[osm_id]:

			modified = False
			modified_tags = []
			nvdb_id = ways_osm[osm_id]['nvdb_id']

			for tag_nvdb in ways_nvdb[ nvdb_id ]['index'].findall("tag"):
				if tag_nvdb.attrib['k'] in merge_tags:
					tag_osm = way.find("tag[@k='%s']" % tag_nvdb.attrib['k'])
					if tag_osm != None:
						if tag_nvdb.attrib['v'] != tag_osm.attrib['v']:
							modified_tags.append("Modified %s=%s to %s" % (tag_nvdb.attrib['k'], tag_osm.attrib['v'], tag_nvdb.attrib['v']))
							tag_osm.set("v", tag_nvdb.attrib['v'])
							modified = True
					else:
						way.append(ElementTree.Element("tag", k=tag_nvdb.attrib['k'], v=tag_nvdb.attrib['v']))
						modified_tags.append("Added %s=%s" % (tag_nvdb.attrib['k'], tag_nvdb.attrib['v']))
						modified = True

			if modified:
				way.set("action", "modify")
				way.append(ElementTree.Element("tag", k="EDIT", v=";".join(modified_tags)))
				if debug:
					way.append(ElementTree.Element("tag", k="NVDBID", v=nvdb_id))
					way.append(ElementTree.Element("tag", k="SWAP", v=str(ways_osm[ osm_id ]['swap_no'])))
					way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(ways_osm[ osm_id ]['distance']))))

	# Transfer new NVDB ways to OSM

	for way in root_nvdb.findall("way"):
		nvdb_id = way.attrib['id']

		if command == "new" and ways_nvdb[ nvdb_id ]['missing'] or \
			command == "replace" and "osm_id" not in ways_nvdb[ nvdb_id ] and (not replace_highway or ways_nvdb[nvdb_id]['highway'] in replace_highway) or \
			command == "offset" and "osm_id" in ways_nvdb[ nvdb_id ]:

			if command == "offset":
				if ways_nvdb[ nvdb_id ]['highway'] != ways_osm[ ways_nvdb[nvdb_id]['osm_id'] ]['highway']:
					tag_highway = way.find("tag[@k='highway']")
					tag_highway.set("v", ways_osm[ ways_nvdb[nvdb_id]['osm_id'] ]['highway'])
					way.append(ElementTree.Element("tag", k="NVDB", v=ways_nvdb[ nvdb_id ]['highway']))
				if debug:
					way.append(ElementTree.Element("tag", k="OSMID", v=ways_nvdb[ nvdb_id ]['osm_id']))
					way.append(ElementTree.Element("tag", k="SWAP", v=str(ways_nvdb[ nvdb_id ]['swap_no'])))
					way.append(ElementTree.Element("tag", k="DISTANCE", v=str(round(ways_nvdb[ nvdb_id ]['distance']))))

			root_osm.append(way)
			for node in ways_nvdb[ nvdb_id ]['nodes']:
				nodes_nvdb[ node ]['used'] += 1

	# Remove OSM nodes which are not used anymore

	for node in root_osm.iter("node"):
		node_id = node.attrib['id']
		tag = node.find("tag")

		if tag == None and nodes_osm[ node_id ]['used'] == 0:
			node.set("action", "delete")

	# Add new NVDB nodes

	for node in root_nvdb.iter("node"):
		node_id = node.attrib['id']
		if node_id in nodes_nvdb and nodes_nvdb[ node_id ]['used'] > 0:
			root_osm.append(node)	

	# Remove nvdb tags

	for way in root_osm.findall("way"):
		tag = way.find("tag[@k='nvdb:id']")
		if tag != None:
			way.remove(tag)
		tag = way.find("tag[@k='nvdb:date']")
		if tag != None:
			way.remove(tag)	

	# Wrap up

	message ("\nSave file ...")

	root_osm.set("generator", "highway_merge v"+version)
	root_osm.set("upload", "false")

	if filename_osm.find(".osm") >= 0:
		filename_out = filename_osm.replace(".osm", "_%s.osm" % command)
	else:
		filename_out = filename_osm + "_%s.osm" % command

	tree_osm.write(filename_out, encoding='utf-8', method='xml', xml_declaration=True)

	message ("\nWritten to file '%s'\n" % filename_out)

	time_lapsed = time.time() - start_time
	message ("Time: %i seconds (%i ways per second)\n" % (time_lapsed, (count_nvdb + count_osm) / time_lapsed))
