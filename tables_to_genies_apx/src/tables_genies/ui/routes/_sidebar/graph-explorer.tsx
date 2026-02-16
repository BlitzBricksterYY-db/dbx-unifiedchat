import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { Suspense, useState, useCallback, useMemo } from 'react';
import { useBuildGraph, useGetGraphDataSuspense, useGetGraphBuildLogs, useCreateGenieRoom, useListGenieRoomsSuspense } from '@/lib/api';
import { selector } from '@/lib/selector';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ArrowLeft, Terminal, X, ChevronDown, ChevronRight, Plus } from 'lucide-react';
import { 
  ReactFlow, 
  Background, 
  Controls, 
  MiniMap,
  Node,
  Edge,
  NodeTypes,
  MarkerType,
  useNodesState,
  useEdgesState,
  Panel,
  EdgeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';

export const Route = createFileRoute('/_sidebar/graph-explorer')({
  component: () => (
    <div>
      <h1 className="text-3xl font-bold mb-6">Explore Graph</h1>
      <GraphExplorerContent />
    </div>
  ),
});

function GraphExplorerContent() {
  const [graphBuilt, setGraphBuilt] = useState(false);
  const buildGraphMutation = useBuildGraph();
  const navigate = useNavigate();

  // Poll logs while building
  const { data: logs } = useGetGraphBuildLogs({
    query: {
      refetchInterval: (query) => {
        return buildGraphMutation.isPending ? 1000 : false;
      },
      enabled: buildGraphMutation.isPending || graphBuilt
    }
  });

  const handleBuildGraph = async () => {
    await buildGraphMutation.mutateAsync();
    setGraphBuilt(true);
  };

  return (
    <div className="space-y-6">
      {!graphBuilt && (
        <Card>
          <CardHeader>
            <CardTitle>Build Table Relationship Graph</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button onClick={handleBuildGraph} disabled={buildGraphMutation.isPending}>
              {buildGraphMutation.isPending ? 'Building...' : 'Build Graph'}
            </Button>

            {buildGraphMutation.isPending && (
              <div className="mt-4 space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                  <Terminal size={16} />
                  <span>Build Logs:</span>
                </div>
                <div className="bg-slate-950 rounded-lg p-4 font-mono text-xs text-slate-300 h-64 overflow-y-auto space-y-1 border border-slate-800 shadow-inner">
                  {logs?.map((log, i) => (
                    <div key={i} className="flex gap-3">
                      <span className="text-slate-500 shrink-0">[{log.timestamp}]</span>
                      <span className={
                        log.level === 'error' ? 'text-red-400' :
                        log.level === 'success' ? 'text-green-400' :
                        'text-slate-300'
                      }>
                        {log.message}
                      </span>
                    </div>
                  ))}
                  {(!logs || logs.length === 0) && (
                    <div className="animate-pulse text-slate-500 italic">Initializing build process...</div>
                  )}
                  <div className="h-1" /> {/* Spacer for scroll to bottom */}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {graphBuilt && (
        <Suspense fallback={<Skeleton className="h-96 w-full" />}>
          <GraphVisualization />
        </Suspense>
      )}

      <div className="flex gap-4">
        <Button variant="outline" onClick={() => navigate({ to: '/enrichment' })}>
          <ArrowLeft size={16} /> Back
        </Button>
        {graphBuilt && (
          <Button onClick={() => navigate({ to: '/genie-builder' })}>
            Next: Build Rooms →
          </Button>
        )}
      </div>
    </div>
  );
}

// Schema color mapping
const SCHEMA_COLORS: Record<string, string> = {
  'demo_mixed': '#ef4444',
  'claims': '#10b981',
  'drug_discovery': '#f59e0b',
  'default': '#3b82f6',
};

// Custom node component
function TableNode({ data }: { data: any }) {
  const schemaColor = SCHEMA_COLORS[data.schema] || SCHEMA_COLORS.default;
  
  return (
    <div 
      className="px-4 py-3 rounded-lg border-2 shadow-lg bg-white dark:bg-slate-800 transition-all hover:shadow-xl hover:scale-105"
      style={{ 
        borderColor: schemaColor,
        minWidth: '180px',
      }}
    >
      <div className="font-semibold text-sm mb-1 text-slate-900 dark:text-slate-100">
        {data.label}
      </div>
      <div className="flex gap-2 items-center">
        <span 
          className="text-xs px-2 py-0.5 rounded-full font-medium"
          style={{ 
            backgroundColor: schemaColor + '20',
            color: schemaColor,
          }}
        >
          {data.schema}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {data.column_count} cols
        </span>
      </div>
    </div>
  );
}

// Custom edge component for semantic edges
function SemanticEdge({ id, sourceX, sourceY, targetX, targetY, style, markerEnd }: any) {
  const edgePath = `M ${sourceX} ${sourceY} L ${targetX} ${targetY}`;
  
  return (
    <g>
      <path
        id={id}
        style={style}
        className="react-flow__edge-path"
        d={edgePath}
        markerEnd={markerEnd}
        strokeDasharray="5,5"
      />
    </g>
  );
}

const nodeTypes: NodeTypes = {
  tableNode: TableNode,
};

const edgeTypes: EdgeTypes = {
  semantic: SemanticEdge,
};

function GraphVisualization() {
  const { data: graphData } = useGetGraphDataSuspense(selector());
  const { data: genieRooms = [] } = useListGenieRoomsSuspense(selector());
  const createRoomMutation = useCreateGenieRoom();
  
  const [hoveredNode, setHoveredNode] = useState<any>(null);
  const [selectedNodes, setSelectedNodes] = useState<Node[]>([]);
  const [expandedColumns, setExpandedColumns] = useState(false);
  const [showSelectionPanel, setShowSelectionPanel] = useState(false);
  const [newRoomName, setNewRoomName] = useState('');
  const [selectedRoomId, setSelectedRoomId] = useState<string>('');

  // Convert Cytoscape format to React Flow format with dagre layout
  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({ rankdir: 'TB', nodesep: 100, ranksep: 150 });

    const nodes: Node[] = [];
    const edges: Edge[] = [];

    // Separate nodes and edges from elements
    graphData.elements.forEach((elem: any) => {
      if (elem.data.source) {
        // It's an edge
        const isSemantic = elem.data.types?.includes('semantic');
        edges.push({
          id: `${elem.data.source}-${elem.data.target}`,
          source: elem.data.source,
          target: elem.data.target,
          type: isSemantic ? 'semantic' : 'default',
          animated: isSemantic,
          style: { 
            stroke: isSemantic ? '#a855f7' : '#cbd5e1',
            strokeWidth: isSemantic ? 3 : 2,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isSemantic ? '#a855f7' : '#cbd5e1',
          },
          data: {
            semantic_reason: elem.data.semantic_reason,
          }
        });
      } else {
        // It's a node
        nodes.push({
          id: elem.data.id,
          type: 'tableNode',
          position: { x: 0, y: 0 }, // Will be set by dagre
          data: elem.data,
        });
        
        // Add to dagre graph for layout
        dagreGraph.setNode(elem.data.id, { width: 200, height: 80 });
      }
    });

    // Add edges to dagre
    edges.forEach((edge) => {
      dagreGraph.setEdge(edge.source, edge.target);
    });

    // Calculate layout
    dagre.layout(dagreGraph);

    // Apply positions from dagre
    nodes.forEach((node) => {
      const dagreNode = dagreGraph.node(node.id);
      node.position = {
        x: dagreNode.x - 100,
        y: dagreNode.y - 40,
      };
    });

    return { nodes, edges };
  }, [graphData]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onNodeMouseEnter = useCallback((_: any, node: Node) => {
    setHoveredNode(node);
  }, []);

  const onNodeMouseLeave = useCallback(() => {
    // Small delay to allow moving to the panel
    setTimeout(() => setHoveredNode(null), 200);
  }, []);

  const onSelectionChange = useCallback(({ nodes }: { nodes: Node[] }) => {
    setSelectedNodes(nodes);
    setShowSelectionPanel(nodes.length > 0);
  }, []);

  const handleRemoveFromSelection = useCallback((nodeId: string) => {
    const updatedNodes = selectedNodes.filter(n => n.id !== nodeId);
    setSelectedNodes(updatedNodes);
    setShowSelectionPanel(updatedNodes.length > 0);
  }, [selectedNodes]);

  const handleAddToRoom = useCallback(async () => {
    const tableFqns = selectedNodes.map(n => n.id);
    
    if (selectedRoomId === 'new' && newRoomName) {
      // Create new room
      await createRoomMutation.mutateAsync({
        data: {
          name: newRoomName,
          table_fqns: tableFqns,
        }
      });
      setNewRoomName('');
      setSelectedRoomId('');
      setShowSelectionPanel(false);
      setSelectedNodes([]);
    } else if (selectedRoomId && selectedRoomId !== 'new') {
      // Add to existing room (in real implementation, would need an update endpoint)
      // For now, create with combined tables
      const existingRoom = genieRooms.find(r => r.id === selectedRoomId);
      if (existingRoom) {
        alert('Adding to existing room - feature coming soon!');
      }
    }
  }, [selectedNodes, selectedRoomId, newRoomName, createRoomMutation, genieRooms]);

  const semanticEdgeCount = edges.filter(e => e.type === 'semantic').length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Table Relationship Graph ({graphData.node_count} tables, {graphData.edge_count} relationships)
        </CardTitle>
        <div className="text-sm text-slate-600 dark:text-slate-400 mt-2 flex gap-4">
          <span className="inline-flex items-center gap-2">
            <span className="w-8 h-0.5 bg-slate-400"></span>
            <span>Structural</span>
          </span>
          {semanticEdgeCount > 0 && (
            <span className="inline-flex items-center gap-2">
              <span className="w-8 h-0.5 bg-purple-500" style={{ borderTop: '2px dashed #a855f7' }}></span>
              <span>Semantic ({semanticEdgeCount} LLM-discovered)</span>
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div style={{ height: '700px' }} className="relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeMouseEnter={onNodeMouseEnter}
            onNodeMouseLeave={onNodeMouseLeave}
            onSelectionChange={onSelectionChange}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            minZoom={0.1}
            maxZoom={2}
            selectNodesOnDrag={false}
          >
            <Background variant="dots" gap={12} size={1} />
            <Controls />
            <MiniMap 
              nodeColor={(node) => {
                const schema = node.data?.schema;
                return SCHEMA_COLORS[schema] || SCHEMA_COLORS.default;
              }}
              maskColor="rgba(0, 0, 0, 0.1)"
            />
            
            {/* Legend Panel */}
            <Panel position="top-left" className="bg-white dark:bg-slate-800 rounded-lg shadow-lg p-3 text-sm">
              <div className="font-semibold mb-2">Communities</div>
              <div className="space-y-1">
                {Object.entries(SCHEMA_COLORS).map(([schema, color]) => (
                  schema !== 'default' && (
                    <div key={schema} className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded" style={{ backgroundColor: color }}></div>
                      <span className="text-xs">{schema}</span>
                    </div>
                  )
                ))}
              </div>
            </Panel>
          </ReactFlow>

          {/* Hover Detail Panel */}
          {hoveredNode && (
            <div 
              className="absolute bottom-0 left-0 right-0 bg-white dark:bg-slate-800 border-t-2 border-slate-200 dark:border-slate-700 shadow-2xl transition-all duration-300 ease-out"
              style={{ 
                transform: hoveredNode ? 'translateY(0)' : 'translateY(100%)',
                maxHeight: '300px',
                overflowY: 'auto',
              }}
              onMouseEnter={() => setHoveredNode(hoveredNode)}
              onMouseLeave={() => setHoveredNode(null)}
            >
              <div className="p-4">
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h3 className="font-bold text-lg text-slate-900 dark:text-slate-100">
                      {hoveredNode.data.label}
                    </h3>
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                      {hoveredNode.id}
                    </p>
                  </div>
                  <Button 
                    variant="ghost" 
                    size="sm"
                    onClick={() => setHoveredNode(null)}
                  >
                    <X size={16} />
                  </Button>
                </div>
                
                {hoveredNode.data.table_description && (
                  <div className="mb-3">
                    <p className="text-sm text-slate-700 dark:text-slate-300">
                      {hoveredNode.data.table_description}
                    </p>
                  </div>
                )}

                {hoveredNode.data.columns && hoveredNode.data.columns.length > 0 && (
                  <div>
                    <button
                      onClick={() => setExpandedColumns(!expandedColumns)}
                      className="flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 mb-2"
                    >
                      {expandedColumns ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      Columns ({hoveredNode.data.columns.length})
                    </button>
                    
                    {expandedColumns && (
                      <div className="space-y-2 ml-6 max-h-40 overflow-y-auto">
                        {hoveredNode.data.columns.map((col: any, idx: number) => (
                          <div key={idx} className="text-sm border-l-2 border-slate-300 dark:border-slate-600 pl-3">
                            <div className="font-mono font-medium text-slate-900 dark:text-slate-100">
                              {col.name} 
                              <span className="text-slate-500 dark:text-slate-400 ml-2 font-normal">
                                {col.type}
                              </span>
                            </div>
                            {col.comment && (
                              <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                                {col.comment}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Selection Action Panel */}
          {showSelectionPanel && (
            <div className="absolute top-4 right-4 bg-white dark:bg-slate-800 rounded-lg shadow-2xl border-2 border-slate-200 dark:border-slate-700 p-4 w-80">
              <div className="flex justify-between items-start mb-3">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">
                  Selected Tables ({selectedNodes.length})
                </h3>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => {
                    setShowSelectionPanel(false);
                    setSelectedNodes([]);
                  }}
                >
                  <X size={16} />
                </Button>
              </div>

              <div className="space-y-2 mb-4 max-h-40 overflow-y-auto">
                {selectedNodes.map((node) => (
                  <div 
                    key={node.id}
                    className="flex items-center justify-between text-sm bg-slate-50 dark:bg-slate-700 rounded px-3 py-2"
                  >
                    <span className="text-slate-900 dark:text-slate-100 truncate">
                      {node.data.label}
                    </span>
                    <button
                      onClick={() => handleRemoveFromSelection(node.id)}
                      className="text-slate-500 hover:text-red-500"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ))}
              </div>

              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-slate-700 dark:text-slate-300 mb-1 block">
                    Add to Genie Room
                  </label>
                  <select
                    value={selectedRoomId}
                    onChange={(e) => setSelectedRoomId(e.target.value)}
                    className="w-full px-3 py-2 text-sm border rounded-md bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
                  >
                    <option value="">Select room...</option>
                    <option value="new">Create New Room</option>
                    {genieRooms.map((room) => (
                      <option key={room.id} value={room.id}>
                        {room.name}
                      </option>
                    ))}
                  </select>
                </div>

                {selectedRoomId === 'new' && (
                  <input
                    type="text"
                    value={newRoomName}
                    onChange={(e) => setNewRoomName(e.target.value)}
                    placeholder="New room name..."
                    className="w-full px-3 py-2 text-sm border rounded-md bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
                  />
                )}

                <Button
                  onClick={handleAddToRoom}
                  disabled={!selectedRoomId || (selectedRoomId === 'new' && !newRoomName) || createRoomMutation.isPending}
                  className="w-full"
                  size="sm"
                >
                  <Plus size={16} className="mr-2" />
                  {createRoomMutation.isPending ? 'Adding...' : 'Add to Room'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
