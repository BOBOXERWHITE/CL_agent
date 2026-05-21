import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import AgentRunsPage from "../../src/pages/AgentRunsPage";

vi.mock("../../src/api/agents", () => ({
  listAgentRuns: vi.fn().mockResolvedValue([
    {
      id: "agent-run-1",
      thread_id: "thread-1",
      agent_name: "policy_supervisor_agent",
      route_name: "policy_qa",
      status: "completed",
      confidence: 0.86,
      requires_human_review: false,
      thread_status: "active",
      pending_interrupt: null,
      latest_checkpoint: {
        id: "checkpoint-1",
        checkpoint_type: "langgraph_state",
        status: "completed",
        created_at: "2026-04-02T00:00:00Z",
      },
      output: {
        answer: "已完成多领域政策拆分。",
        specialist: "mixed_policy_supervisor",
        specialist_plan: [
          "hotel_policy_agent",
          "flight_policy_agent",
          "reimbursement_policy_agent",
        ],
        profile_reports: [
          {
            domain: "hotel",
            label: "Hotel",
            primary_answer: "酒店域结论：北京 L2 每晚标准 700 元。",
            missing_dimensions: [],
            coverage: {
              required_dimensions: ["room_rate_standard"],
              covered_dimensions: ["room_rate_standard"],
              coverage_ratio: 1,
            },
          },
          {
            domain: "flight",
            label: "Flight",
            primary_answer: "机票域结论：business class 需要审批。",
            missing_dimensions: [],
            coverage: {
              required_dimensions: ["cabin_policy", "approval_requirement"],
              covered_dimensions: ["cabin_policy", "approval_requirement"],
              coverage_ratio: 1,
            },
          },
        ],
        orchestration_trace: {
          agent_name: "policy_supervisor_agent",
          route_name: "policy_qa",
          thread_id: "thread-1",
          thread_status: "active",
          trace_events: [
            {
              category: "router",
              name: "route_decision",
              status: "completed",
              detail: "mixed policy domains detected",
              timestamp: "2026-04-02T00:00:00Z",
              metadata: { planned_domains: ["hotel", "flight", "reimbursement"] },
            },
          ],
          router: {
            domain: "mixed",
            specialist: "mixed_policy_supervisor",
            planned_domains: ["hotel", "flight", "reimbursement"],
          },
          specialist_plan: [
            "hotel_policy_agent",
            "flight_policy_agent",
            "reimbursement_policy_agent",
          ],
          coverage: {
            required_dimensions: [
              "hotel.room_rate_standard",
              "flight.cabin_policy",
              "flight.approval_requirement",
            ],
            covered_dimensions: [
              "hotel.room_rate_standard",
              "flight.cabin_policy",
              "flight.approval_requirement",
            ],
            coverage_ratio: 1,
            per_domain: {
              hotel: {
                required_dimensions: ["room_rate_standard"],
                covered_dimensions: ["room_rate_standard"],
                coverage_ratio: 1,
              },
              flight: {
                required_dimensions: ["cabin_policy", "approval_requirement"],
                covered_dimensions: ["cabin_policy", "approval_requirement"],
                coverage_ratio: 1,
              },
            },
          },
          tool_calls: [{ tool_name: "policy_search", status: "completed", latency_ms: 3 }],
        },
        coverage: {
          required_dimensions: [
            "hotel.room_rate_standard",
            "flight.cabin_policy",
            "flight.approval_requirement",
          ],
          covered_dimensions: [
            "hotel.room_rate_standard",
            "flight.cabin_policy",
            "flight.approval_requirement",
          ],
          coverage_ratio: 1,
          per_domain: {
            hotel: {
              required_dimensions: ["room_rate_standard"],
              covered_dimensions: ["room_rate_standard"],
              coverage_ratio: 1,
            },
            flight: {
              required_dimensions: ["cabin_policy", "approval_requirement"],
              covered_dimensions: ["cabin_policy", "approval_requirement"],
              coverage_ratio: 1,
            },
          },
        },
        missing_dimensions: [],
      },
      timeline: [
        {
          node_name: "router",
          status: "completed",
          detail: "detected mixed-domain policy question",
          timestamp: "2026-04-02T00:00:00Z",
        },
      ],
      tool_calls: [
        {
          tool_name: "policy_search",
          status: "completed",
          latency_ms: 3,
          input_payload: {
            question: "北京酒店 760 元含早，同时国内机票想订 business class。",
          },
          output_payload: {
            answer: "stubbed",
          },
        },
      ],
      created_at: "2026-04-02T00:00:00Z",
      updated_at: "2026-04-02T00:00:00Z",
    },
    {
      id: "agent-run-ticket-1",
      thread_id: "thread-ticket-1",
      agent_name: "ticket_router_agent",
      route_name: "ticket_triage",
      status: "needs_review",
      confidence: 0.86,
      requires_human_review: true,
      thread_status: "awaiting_review",
      pending_interrupt: {
        kind: "human_review",
        reason: "ticket routing requires operator review",
        queue_name: "finance-review",
        allowed_decisions: ["approve", "edit", "reject"],
      },
      latest_checkpoint: {
        id: "checkpoint-ticket-1",
        checkpoint_type: "engine_adapter_state",
        status: "paused",
        created_at: "2026-04-02T00:00:00Z",
      },
      output: {
        queue_name: "finance-review",
        reason: "酒店报销单超标，需要进入财务复核队列。",
        orchestration_trace: {
          agent_name: "ticket_router_agent",
          route_name: "ticket_triage",
          thread_id: "thread-ticket-1",
          queue_name: "finance-review",
          trace_events: [
            {
              category: "interrupt",
              name: "human_review",
              status: "paused",
              detail: "ticket routing requires operator review",
              timestamp: "2026-04-02T00:00:00Z",
              metadata: {
                queue_name: "finance-review",
                allowed_decisions: ["approve", "edit", "reject"],
              },
            },
            {
              category: "checkpoint",
              name: "checkpoint_state",
              status: "paused",
              detail: "engine_adapter_state",
              timestamp: "2026-04-02T00:00:00Z",
              metadata: {
                checkpoint_id: "checkpoint-ticket-1",
              },
            },
          ],
          pending_interrupt: {
            kind: "human_review",
            reason: "ticket routing requires operator review",
            queue_name: "finance-review",
            allowed_decisions: ["approve", "edit", "reject"],
          },
          latest_checkpoint: {
            id: "checkpoint-ticket-1",
            checkpoint_type: "engine_adapter_state",
            status: "paused",
            created_at: "2026-04-02T00:00:00Z",
          },
          timeline_nodes: [
            { node_name: "router", status: "completed" },
            { node_name: "ticket_triage", status: "completed" },
          ],
          tool_calls: [
            { tool_name: "ticket_queue_lookup", status: "completed", latency_ms: 4 },
          ],
        },
      },
      timeline: [
        {
          node_name: "router",
          status: "completed",
          detail: "ticket payload short-circuited to ticket route",
          timestamp: "2026-04-02T00:00:00Z",
        },
      ],
      tool_calls: [
        {
          tool_name: "ticket_queue_lookup",
          status: "completed",
          latency_ms: 4,
          input_payload: { ticket_id: "ticket-1" },
          output_payload: { queue_name: "finance-review" },
        },
      ],
      created_at: "2026-04-02T00:00:00Z",
      updated_at: "2026-04-02T00:00:00Z",
    },
  ]),
  createAgentRun: vi.fn(),
}));

test("renders mixed-domain specialist plan and domain reports", async () => {
  render(<AgentRunsPage />);

  expect((await screen.findAllByText("policy_supervisor_agent")).length).toBeGreaterThan(0);
  expect(screen.getByText("mixed_policy_supervisor")).toBeInTheDocument();
  expect(screen.getByText("hotel_policy_agent")).toBeInTheDocument();
  expect(screen.getByText("flight_policy_agent")).toBeInTheDocument();
  expect(screen.getByText("reimbursement_policy_agent")).toBeInTheDocument();
  expect(screen.getByText("Hotel")).toBeInTheDocument();
  expect(screen.getByText("Flight")).toBeInTheDocument();
  expect(screen.getByText("policy_search")).toBeInTheDocument();
  expect(screen.getByText("langgraph_state")).toBeInTheDocument();
});

test("renders orchestration trace drawer for ticket runs", async () => {
  render(<AgentRunsPage />);

  expect((await screen.findAllByText("ticket_router_agent")).length).toBeGreaterThan(0);
  const traceButtons = await screen.findAllByRole("button", { name: "查看 Trace" });
  fireEvent.click(traceButtons[1]);

  expect(screen.getAllByText("ticket_triage").length).toBeGreaterThan(0);
  expect(screen.getAllByText("engine_adapter_state").length).toBeGreaterThan(0);
  expect(screen.getAllByText("finance-review").length).toBeGreaterThan(0);
  expect(screen.getAllByText("ticket routing requires operator review").length).toBeGreaterThan(0);
  expect(screen.getAllByText("ticket_queue_lookup").length).toBeGreaterThan(0);
  expect(screen.getByText("Trace Events")).toBeInTheDocument();
  expect(screen.getAllByText("human_review").length).toBeGreaterThan(0);
  expect(screen.getAllByText("checkpoint_state").length).toBeGreaterThan(0);
});
