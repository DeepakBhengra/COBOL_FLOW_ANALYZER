       IDENTIFICATION DIVISION.
       PROGRAM-ID. CUSTINQ.
      * Customer inquiry, pseudo-conversational, with a COMMAREA from the caller.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-RESP         PIC S9(8) COMP.
       01 WS-CUST-REC.
          05 WS-CUST-NAME PIC X(30).
          05 WS-CUST-BAL  PIC S9(9)V99 COMP-3.
       LINKAGE SECTION.
       01 DFHCOMMAREA.
          05 CA-ACTION        PIC X(1).
          05 CA-CUST-ID       PIC X(8).
          05 CA-RETURN-CODE   PIC 9(2).
          05 CA-CUST-NAME     PIC X(30).
          05 CA-CUST-BALANCE  PIC S9(9)V99 COMP-3.
          05 CA-MESSAGE       PIC X(60).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF EIBCALEN = 0
               PERFORM FIRST-TIME-PARA
           ELSE
               PERFORM PROCESS-REQUEST
           END-IF.
           EXEC CICS RETURN TRANSID('CUST')
                COMMAREA(DFHCOMMAREA)
                LENGTH(LENGTH OF DFHCOMMAREA)
           END-EXEC.
       FIRST-TIME-PARA.
           MOVE SPACES TO CA-MESSAGE.
           MOVE 'Enter customer id' TO CA-MESSAGE.
           MOVE 0 TO CA-RETURN-CODE.
       PROCESS-REQUEST.
           IF CA-CUST-ID = SPACES
               MOVE 90 TO CA-RETURN-CODE
               MOVE 'Customer id required' TO CA-MESSAGE
           ELSE
               PERFORM READ-CUSTOMER
           END-IF.
           IF CA-ACTION = 'B'
               PERFORM CALL-BALANCE
           END-IF.
       READ-CUSTOMER.
           EXEC CICS READ FILE('CUSTMAST')
                INTO(WS-CUST-REC)
                RIDFLD(CA-CUST-ID)
                RESP(WS-RESP)
           END-EXEC.
           IF WS-RESP = 0
               MOVE WS-CUST-NAME TO CA-CUST-NAME
               MOVE WS-CUST-BAL TO CA-CUST-BALANCE
               MOVE 0 TO CA-RETURN-CODE
           ELSE
               MOVE 91 TO CA-RETURN-CODE
               MOVE 'Customer not found' TO CA-MESSAGE
           END-IF.
       CALL-BALANCE.
           EXEC CICS LINK PROGRAM('BALCALC')
                COMMAREA(DFHCOMMAREA)
                LENGTH(LENGTH OF DFHCOMMAREA)
           END-EXEC.
