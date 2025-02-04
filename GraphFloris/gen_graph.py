import dgl
import numpy as np
import torch


def get_node_only_graph(xs, ys):
    g = dgl.graph(data=([], []), num_nodes=0)  # an empty graph
    num_nodes = len(xs)

    g.add_nodes(num_nodes, {'x': torch.tensor(xs).view(-1, 1),
                            'y': torch.tensor(ys).view(-1, 1)})
    return g


def update_edges(g, wind_direction, influence_angle_th, influence_dist, influence_radius=0):
    # generate all possible edges and delete edges by conditions

    u, v = [], []
    for i in range(g.number_of_nodes()):
        for j in range(g.number_of_nodes()):
            if i == j:
                continue  # Ignore self-loop
            else:
                u.append(i)
                v.append(j)

    g.add_edges(u, v)

    # compute distance
    def compute_euclidean_dist(edges):
        src_x, src_y = edges.src['x'], edges.src['y']
        dst_x, dst_y = edges.dst['x'], edges.dst['y']
        dist = torch.norm(torch.cat([src_x - dst_x, src_y - dst_y], dim=-1), dim=-1, keepdim=True)
        return {'dist': dist}

    g.apply_edges(func=compute_euclidean_dist)

    # compute 'is-in-influential region'
    def compute_is_influential(edges):
        # 1. translate dst nodes so that source node places on the origin
        # 2. rotate the dst nodes counter-clockwise by 'wd' degree
        # 3. check the dst nodes in the influential region of the source nodes
        # 4. compute downstream and radial wake distances

        src_x, src_y = edges.src['x'], edges.src['y']
        dst_x, dst_y = edges.dst['x'], edges.dst['y']

        tslr_dst_x, tslr_dst_y = dst_x - src_x, dst_y - src_y

        rad_wd = np.radians(wind_direction)

        R = np.array(([np.cos(rad_wd), -np.sin(rad_wd)],
                      [np.sin(rad_wd), np.cos(rad_wd)]))  # ccw 'wd' matrix
        R = torch.tensor(R).float()  # [2, 2]
        tslr_xy = torch.cat([tslr_dst_x, tslr_dst_y], dim=1)
        rotated_dst_xy = torch.einsum('ij, bj -> bi', R, tslr_xy)
        r_dst_x, r_dst_y = rotated_dst_xy.split(1, dim=1)  # WARNING: radial is x and down-stream is y

        a = np.abs(round(np.tan(np.radians(90 - influence_angle_th)), 10))

        is_in_influential_cone1 = (r_dst_y <= a * r_dst_x)
        is_in_influential_cone2 = (r_dst_y <= -a * r_dst_x)
        is_in_influential_cone = is_in_influential_cone1 & is_in_influential_cone2
        is_in_influential_cylinder = (torch.abs(r_dst_x) <= influence_radius) & (r_dst_y < 0)  # close to axis and downstream
        is_in_influential_dist = edges.data['dist'] <= influence_dist
        is_in_influential_region = (is_in_influential_cone | is_in_influential_cylinder) & is_in_influential_dist
        # Absolute distances
        # down_stream_dist = torch.abs(r_dst_y)
        # radial_dist = torch.abs(r_dst_x)
        # Removing absolute values
        down_stream_dist = -r_dst_y
        radial_dist = -r_dst_x
        return {'is_in_influential_region': is_in_influential_region,
                'down_stream_dist': down_stream_dist,
                'radial_dist': radial_dist}

    g.apply_edges(func=compute_is_influential)
    # delete edges
    not_influential_eids = np.arange(g.number_of_edges())[~g.edata['is_in_influential_region'].view(-1)]
    g.remove_edges(not_influential_eids)
